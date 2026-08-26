from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from app.brokers import ExecutionResult
from app.models import OrderPlan, Position, Product, Side


class PersistentPaperBroker:
    """Transaction-safe paper broker with idempotent order execution."""

    def __init__(self, path: str | Path, starting_cash: float) -> None:
        if starting_cash <= 0:
            raise ValueError("starting_cash must be positive")
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.starting_cash = starting_cash
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    @staticmethod
    def _migrate_order_columns(connection: sqlite3.Connection) -> None:
        columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(paper_orders)").fetchall()
        }
        migrations = {
            "executed_at": "ALTER TABLE paper_orders ADD COLUMN executed_at TEXT NOT NULL DEFAULT ''",
            "realized_pnl": "ALTER TABLE paper_orders ADD COLUMN realized_pnl REAL NOT NULL DEFAULT 0",
            "reference_average_price": (
                "ALTER TABLE paper_orders ADD COLUMN reference_average_price REAL"
            ),
        }
        for column, statement in migrations.items():
            if column not in columns:
                connection.execute(statement)

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS account (
                    singleton_id INTEGER PRIMARY KEY CHECK(singleton_id = 1),
                    cash REAL NOT NULL CHECK(cash >= 0)
                );

                CREATE TABLE IF NOT EXISTS positions (
                    symbol TEXT NOT NULL,
                    product TEXT NOT NULL,
                    quantity INTEGER NOT NULL CHECK(quantity > 0),
                    average_price REAL NOT NULL CHECK(average_price > 0),
                    PRIMARY KEY(symbol, product)
                );

                CREATE TABLE IF NOT EXISTS paper_orders (
                    order_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    intent_id TEXT NOT NULL UNIQUE,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    product TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    price REAL NOT NULL,
                    status TEXT NOT NULL,
                    filled_quantity INTEGER NOT NULL,
                    executed_at TEXT NOT NULL DEFAULT '',
                    realized_pnl REAL NOT NULL DEFAULT 0,
                    reference_average_price REAL
                );
                """
            )
            self._migrate_order_columns(connection)
            connection.execute(
                """
                INSERT OR IGNORE INTO account(singleton_id, cash)
                VALUES (1, ?)
                """,
                (self.starting_cash,),
            )

    def get_cash(self) -> float:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT cash FROM account WHERE singleton_id = 1"
            ).fetchone()
        if row is None:
            raise RuntimeError("paper account is missing")
        return float(row["cash"])

    def get_positions(self) -> list[Position]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT symbol, product, quantity, average_price
                FROM positions
                ORDER BY symbol, product
                """
            ).fetchall()
        return [
            Position(
                symbol=str(row["symbol"]),
                product=Product(str(row["product"])),
                quantity=int(row["quantity"]),
                average_price=float(row["average_price"]),
            )
            for row in rows
        ]

    @staticmethod
    def _result_from_row(row: sqlite3.Row) -> ExecutionResult:
        return ExecutionResult(
            order_id=f"paper-{int(row['order_id'])}",
            status=str(row["status"]),
            filled_quantity=int(row["filled_quantity"]),
            average_price=float(row["price"]),
        )

    def place_order(self, plan: OrderPlan) -> ExecutionResult:
        if plan.limit_price is None:
            raise ValueError("PersistentPaperBroker requires a limit price")
        if plan.side == Side.HOLD:
            raise ValueError("HOLD is not executable")

        price = plan.limit_price
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing_order = connection.execute(
                "SELECT * FROM paper_orders WHERE intent_id = ?",
                (plan.intent_id,),
            ).fetchone()
            if existing_order is not None:
                return self._result_from_row(existing_order)

            account = connection.execute(
                "SELECT cash FROM account WHERE singleton_id = 1"
            ).fetchone()
            if account is None:
                raise RuntimeError("paper account is missing")
            cash = float(account["cash"])
            position = connection.execute(
                """
                SELECT quantity, average_price
                FROM positions
                WHERE symbol = ? AND product = ?
                """,
                (plan.symbol, plan.product.value),
            ).fetchone()
            current_qty = int(position["quantity"]) if position is not None else 0
            current_avg = float(position["average_price"]) if position is not None else price
            notional = price * plan.quantity
            realized_pnl = 0.0

            if plan.side == Side.BUY:
                if notional > cash:
                    raise ValueError("Insufficient paper cash")
                new_qty = current_qty + plan.quantity
                new_avg = ((current_qty * current_avg) + notional) / new_qty
                connection.execute(
                    "UPDATE account SET cash = ? WHERE singleton_id = 1",
                    (cash - notional,),
                )
                connection.execute(
                    """
                    INSERT INTO positions(symbol, product, quantity, average_price)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(symbol, product) DO UPDATE SET
                        quantity=excluded.quantity,
                        average_price=excluded.average_price
                    """,
                    (plan.symbol, plan.product.value, new_qty, new_avg),
                )
            else:
                if position is None or current_qty < plan.quantity:
                    raise ValueError("Cannot sell more than the paper position")
                new_qty = current_qty - plan.quantity
                realized_pnl = (price - current_avg) * plan.quantity
                connection.execute(
                    "UPDATE account SET cash = ? WHERE singleton_id = 1",
                    (cash + notional,),
                )
                if new_qty == 0:
                    connection.execute(
                        "DELETE FROM positions WHERE symbol = ? AND product = ?",
                        (plan.symbol, plan.product.value),
                    )
                else:
                    connection.execute(
                        """
                        UPDATE positions SET quantity = ?
                        WHERE symbol = ? AND product = ?
                        """,
                        (new_qty, plan.symbol, plan.product.value),
                    )

            cursor = connection.execute(
                """
                INSERT INTO paper_orders(
                    intent_id, symbol, side, product, quantity, price, status,
                    filled_quantity, executed_at, realized_pnl, reference_average_price
                ) VALUES (?, ?, ?, ?, ?, ?, 'FILLED', ?, ?, ?, ?)
                """,
                (
                    plan.intent_id,
                    plan.symbol,
                    plan.side.value,
                    plan.product.value,
                    plan.quantity,
                    price,
                    plan.quantity,
                    datetime.now(UTC).isoformat(),
                    realized_pnl,
                    current_avg,
                ),
            )
            order_id = cursor.lastrowid
            if order_id is None:
                raise RuntimeError("paper order insert did not return an id")
            return ExecutionResult(
                order_id=f"paper-{int(order_id)}",
                status="FILLED",
                filled_quantity=plan.quantity,
                average_price=price,
            )
