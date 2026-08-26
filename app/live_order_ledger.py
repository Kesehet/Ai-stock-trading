from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.models import OrderPlan, Position, Product, Side


@dataclass(frozen=True)
class LiveOrderRecord:
    intent_id: str
    broker_order_id: str
    symbol: str
    side: Side
    product: Product
    quantity: int
    status: str
    filled_quantity: int
    average_price: float
    created_at: datetime
    updated_at: datetime


class LiveOrderLedger:
    """Fail-closed idempotency and bot-owned live portfolio ledger."""

    _PENDING_STATUSES = (
        "PENDING_SEND",
        "UNKNOWN",
        "SUBMITTED",
        "OPEN",
        "TRIGGER PENDING",
        "AMO REQ RECEIVED",
        "VALIDATION PENDING",
        "CANCEL_REQUESTED",
    )

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS live_orders (
                    intent_id TEXT PRIMARY KEY,
                    broker_order_id TEXT NOT NULL DEFAULT '',
                    symbol TEXT NOT NULL DEFAULT '',
                    side TEXT NOT NULL DEFAULT 'BUY',
                    product TEXT NOT NULL DEFAULT 'DELIVERY',
                    quantity INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL,
                    filled_quantity INTEGER NOT NULL DEFAULT 0,
                    average_price REAL NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._migrate(connection)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    @staticmethod
    def _migrate(connection: sqlite3.Connection) -> None:
        existing = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(live_orders)").fetchall()
        }
        definitions = {
            "symbol": "TEXT NOT NULL DEFAULT ''",
            "side": "TEXT NOT NULL DEFAULT 'BUY'",
            "product": "TEXT NOT NULL DEFAULT 'DELIVERY'",
            "quantity": "INTEGER NOT NULL DEFAULT 0",
            "filled_quantity": "INTEGER NOT NULL DEFAULT 0",
            "average_price": "REAL NOT NULL DEFAULT 0",
        }
        for column, definition in definitions.items():
            if column not in existing:
                connection.execute(
                    f"ALTER TABLE live_orders ADD COLUMN {column} {definition}"
                )

    def claim(self, plan: OrderPlan) -> bool:
        now = datetime.now(UTC).isoformat()
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO live_orders(
                        intent_id, symbol, side, product, quantity,
                        status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 'PENDING_SEND', ?, ?)
                    """,
                    (
                        plan.intent_id,
                        plan.symbol,
                        plan.side.value,
                        plan.product.value,
                        plan.quantity,
                        now,
                        now,
                    ),
                )
        except sqlite3.IntegrityError:
            return False
        return True

    def update(
        self,
        intent_id: str,
        *,
        broker_order_id: str = "",
        status: str,
        filled_quantity: int | None = None,
        average_price: float | None = None,
    ) -> None:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE live_orders
                SET broker_order_id = CASE WHEN ? = '' THEN broker_order_id ELSE ? END,
                    status = ?,
                    filled_quantity = COALESCE(?, filled_quantity),
                    average_price = COALESCE(?, average_price),
                    updated_at = ?
                WHERE intent_id = ?
                """,
                (
                    broker_order_id,
                    broker_order_id,
                    status,
                    filled_quantity,
                    average_price,
                    datetime.now(UTC).isoformat(),
                    intent_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError("live intent is not registered")

    @staticmethod
    def _row(row: sqlite3.Row) -> LiveOrderRecord:
        return LiveOrderRecord(
            intent_id=str(row["intent_id"]),
            broker_order_id=str(row["broker_order_id"]),
            symbol=str(row["symbol"]),
            side=Side(str(row["side"])),
            product=Product(str(row["product"])),
            quantity=int(row["quantity"]),
            status=str(row["status"]),
            filled_quantity=int(row["filled_quantity"]),
            average_price=float(row["average_price"]),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )

    def get(self, intent_id: str) -> LiveOrderRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM live_orders WHERE intent_id = ?",
                (intent_id,),
            ).fetchone()
        return self._row(row) if row is not None else None

    def pending(self) -> list[LiveOrderRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM live_orders
                WHERE status IN (?, ?, ?, ?, ?, ?, ?, ?)
                ORDER BY created_at
                """,
                self._PENDING_STATUSES,
            ).fetchall()
        return [self._row(row) for row in rows]

    def completed(self) -> list[LiveOrderRecord]:
        """Return all known fills, including partial fills of cancelled/open orders."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM live_orders WHERE filled_quantity > 0 ORDER BY created_at"
            ).fetchall()
        return [self._row(row) for row in rows]

    def managed_positions(self) -> list[Position]:
        state: dict[tuple[str, Product], tuple[int, float]] = {}
        for record in self.completed():
            qty = record.filled_quantity
            if qty <= 0 or record.average_price <= 0:
                continue
            key = (record.symbol, record.product)
            current_qty, current_avg = state.get(key, (0, record.average_price))
            if record.side == Side.BUY:
                new_qty = current_qty + qty
                new_avg = (
                    (current_qty * current_avg) + (qty * record.average_price)
                ) / new_qty
                state[key] = (new_qty, new_avg)
            else:
                new_qty = max(0, current_qty - qty)
                if new_qty == 0:
                    state.pop(key, None)
                else:
                    state[key] = (new_qty, current_avg)
        return [
            Position(symbol=symbol, product=product, quantity=qty, average_price=avg)
            for (symbol, product), (qty, avg) in sorted(state.items())
            if qty > 0
        ]

    def managed_cash(self, starting_cash: float) -> float:
        cash = starting_cash
        for record in self.completed():
            value = record.filled_quantity * record.average_price
            if record.side == Side.BUY:
                cash -= value
            else:
                cash += value
        return max(0.0, cash)
