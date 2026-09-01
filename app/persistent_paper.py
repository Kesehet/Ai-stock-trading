from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.brokers import ExecutionResult
from app.costs import EquityChargeSchedule
from app.models import OrderPlan, Position, Product, Side

IST = ZoneInfo("Asia/Kolkata")


class PersistentPaperBroker:
    """Transaction-safe paper broker with idempotent, cost-aware execution."""

    def __init__(
        self,
        path: str | Path,
        starting_cash: float,
        *,
        slippage_bps: float = 0.0,
        charge_schedule: EquityChargeSchedule | None = None,
    ) -> None:
        if starting_cash <= 0:
            raise ValueError("starting_cash must be positive")
        if slippage_bps < 0:
            raise ValueError("slippage_bps cannot be negative")
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.starting_cash = starting_cash
        self.slippage_bps = slippage_bps
        self.charge_schedule = charge_schedule
        self._initialize()

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)

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
            "executed_at": (
                "ALTER TABLE paper_orders ADD COLUMN executed_at "
                "TEXT NOT NULL DEFAULT ''"
            ),
            "realized_pnl": (
                "ALTER TABLE paper_orders ADD COLUMN realized_pnl "
                "REAL NOT NULL DEFAULT 0"
            ),
            "reference_average_price": (
                "ALTER TABLE paper_orders ADD COLUMN reference_average_price REAL"
            ),
            "charges": "ALTER TABLE paper_orders ADD COLUMN charges REAL NOT NULL DEFAULT 0",
            "charge_treatment": (
                "ALTER TABLE paper_orders ADD COLUMN charge_treatment "
                "TEXT NOT NULL DEFAULT 'delivery'"
            ),
        }
        for column, statement in migrations.items():
            if column not in columns:
                connection.execute(statement)

    @staticmethod
    def _migrate_account_columns(connection: sqlite3.Connection) -> None:
        columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(account)").fetchall()
        }
        if "initial_cash" not in columns:
            connection.execute("ALTER TABLE account ADD COLUMN initial_cash REAL")

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS account (
                    singleton_id INTEGER PRIMARY KEY CHECK(singleton_id = 1),
                    cash REAL NOT NULL CHECK(cash >= 0),
                    initial_cash REAL
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
                    reference_average_price REAL,
                    charges REAL NOT NULL DEFAULT 0,
                    charge_treatment TEXT NOT NULL DEFAULT 'delivery'
                );

                CREATE TABLE IF NOT EXISTS paper_dp_charges (
                    trade_date TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    PRIMARY KEY(trade_date, symbol)
                );
                """
            )
            self._migrate_account_columns(connection)
            self._migrate_order_columns(connection)
            connection.execute(
                """
                INSERT OR IGNORE INTO account(singleton_id, cash, initial_cash)
                VALUES (1, ?, ?)
                """,
                (self.starting_cash, self.starting_cash),
            )
            row = connection.execute(
                "SELECT initial_cash FROM account WHERE singleton_id = 1"
            ).fetchone()
            configured = None if row is None else row["initial_cash"]
            if configured is None or float(configured) != float(self.starting_cash):
                connection.execute("DELETE FROM positions")
                connection.execute("DELETE FROM paper_orders")
                connection.execute("DELETE FROM paper_dp_charges")
                connection.execute(
                    "UPDATE account SET cash = ?, initial_cash = ? WHERE singleton_id = 1",
                    (self.starting_cash, self.starting_cash),
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

    def _execution_price(self, plan: OrderPlan) -> float:
        if plan.limit_price is None:
            raise ValueError("PersistentPaperBroker requires a limit price")
        slip = self.slippage_bps / 10_000
        if plan.side == Side.BUY:
            return round(plan.limit_price * (1 + slip), 2)
        return round(plan.limit_price * (1 - slip), 2)

    def _charges(
        self,
        *,
        turnover: float,
        side: Side,
        product: Product,
        include_dp: bool = False,
    ) -> float:
        if self.charge_schedule is None:
            return 0.0
        return self.charge_schedule.charges(
            turnover=turnover,
            side=side,
            product=product,
            include_dp=include_dp,
        )

    @staticmethod
    def _trade_date(now: datetime) -> str:
        return now.astimezone(IST).date().isoformat()

    def _same_day_delivery_quantities(
        self,
        connection: sqlite3.Connection,
        symbol: str,
        trade_date: str,
    ) -> tuple[int, int]:
        row = connection.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN side = 'BUY' THEN filled_quantity ELSE 0 END), 0) AS buys,
                COALESCE(SUM(CASE WHEN side = 'SELL' THEN filled_quantity ELSE 0 END), 0) AS sells
            FROM paper_orders
            WHERE symbol = ? AND product = ?
              AND date(datetime(executed_at), '+5 hours', '+30 minutes') = ?
            """,
            (symbol, Product.DELIVERY.value, trade_date),
        ).fetchone()
        return int(row["buys"]), int(row["sells"])

    def _reclassify_same_day_buys_as_intraday(
        self,
        connection: sqlite3.Connection,
        *,
        symbol: str,
        trade_date: str,
        current_qty: int,
        current_avg: float,
    ) -> tuple[float, float]:
        if self.charge_schedule is None:
            return current_avg, 0.0
        rows = connection.execute(
            """
            SELECT order_id, price, filled_quantity, charges
            FROM paper_orders
            WHERE symbol = ? AND product = ? AND side = 'BUY'
              AND charge_treatment = 'delivery'
              AND date(datetime(executed_at), '+5 hours', '+30 minutes') = ?
            """,
            (symbol, Product.DELIVERY.value, trade_date),
        ).fetchall()
        refund = 0.0
        for row in rows:
            turnover = float(row["price"]) * int(row["filled_quantity"])
            corrected = self._charges(
                turnover=turnover,
                side=Side.BUY,
                product=Product.INTRADAY,
            )
            previous = float(row["charges"])
            refund += previous - corrected
            connection.execute(
                (
                    "UPDATE paper_orders SET charges = ?, "
                    "charge_treatment = 'intraday' WHERE order_id = ?"
                ),
                (corrected, int(row["order_id"])),
            )
        adjusted_avg = current_avg
        if current_qty > 0 and refund != 0:
            adjusted_avg = current_avg - (refund / current_qty)
            connection.execute(
                "UPDATE positions SET average_price = ? WHERE symbol = ? AND product = ?",
                (adjusted_avg, symbol, Product.DELIVERY.value),
            )
        return adjusted_avg, refund

    def place_order(self, plan: OrderPlan) -> ExecutionResult:
        if plan.limit_price is None:
            raise ValueError("PersistentPaperBroker requires a limit price")
        if plan.side == Side.HOLD:
            raise ValueError("HOLD is not executable")

        now = self._now()
        price = self._execution_price(plan)
        trade_date = self._trade_date(now)
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
                SELECT quantity, average_price FROM positions
                WHERE symbol = ? AND product = ?
                """,
                (plan.symbol, plan.product.value),
            ).fetchone()
            current_qty = int(position["quantity"]) if position is not None else 0
            current_avg = float(position["average_price"]) if position is not None else price
            notional = price * plan.quantity
            realized_pnl = 0.0
            charge_treatment = plan.product.value.lower()

            if plan.side == Side.BUY:
                charges = self._charges(
                    turnover=notional,
                    side=plan.side,
                    product=plan.product,
                )
                total_cost = notional + charges
                if total_cost > cash:
                    raise ValueError("Insufficient paper cash")
                new_qty = current_qty + plan.quantity
                new_avg = ((current_qty * current_avg) + total_cost) / new_qty
                connection.execute(
                    "UPDATE account SET cash = ? WHERE singleton_id = 1",
                    (cash - total_cost,),
                )
                connection.execute(
                    """
                    INSERT INTO positions(symbol, product, quantity, average_price)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(symbol, product) DO UPDATE SET
                        quantity=excluded.quantity, average_price=excluded.average_price
                    """,
                    (plan.symbol, plan.product.value, new_qty, new_avg),
                )
            else:
                if position is None or current_qty < plan.quantity:
                    raise ValueError("Cannot sell more than the paper position")

                buy_refund = 0.0
                original_avg = current_avg
                if plan.product == Product.DELIVERY:
                    same_day_buys, same_day_sells = self._same_day_delivery_quantities(
                        connection, plan.symbol, trade_date
                    )
                    same_day_available = max(0, same_day_buys - same_day_sells)
                    intraday_qty = min(plan.quantity, same_day_available)
                    delivery_qty = plan.quantity - intraday_qty

                    if intraday_qty > 0:
                        current_avg, buy_refund = self._reclassify_same_day_buys_as_intraday(
                            connection,
                            symbol=plan.symbol,
                            trade_date=trade_date,
                            current_qty=current_qty,
                            current_avg=current_avg,
                        )
                    intraday_turnover = price * intraday_qty
                    delivery_turnover = price * delivery_qty
                    intraday_charges = self._charges(
                        turnover=intraday_turnover,
                        side=Side.SELL,
                        product=Product.INTRADAY,
                    )
                    include_dp = False
                    if delivery_qty > 0:
                        dp_row = connection.execute(
                            "SELECT 1 FROM paper_dp_charges WHERE trade_date = ? AND symbol = ?",
                            (trade_date, plan.symbol),
                        ).fetchone()
                        include_dp = dp_row is None
                    delivery_charges = self._charges(
                        turnover=delivery_turnover,
                        side=Side.SELL,
                        product=Product.DELIVERY,
                        include_dp=include_dp,
                    )
                    charges = intraday_charges + delivery_charges
                    if include_dp:
                        connection.execute(
                            (
                                "INSERT OR IGNORE INTO paper_dp_charges"
                                "(trade_date, symbol) VALUES (?, ?)"
                            ),
                            (trade_date, plan.symbol),
                        )
                    if intraday_qty and delivery_qty:
                        charge_treatment = "mixed"
                    elif intraday_qty:
                        charge_treatment = "intraday"
                    else:
                        charge_treatment = "delivery"
                else:
                    charges = self._charges(
                        turnover=notional,
                        side=plan.side,
                        product=plan.product,
                    )

                new_qty = current_qty - plan.quantity
                net_proceeds = notional - charges + buy_refund
                realized_pnl = net_proceeds - (original_avg * plan.quantity)
                connection.execute(
                    "UPDATE account SET cash = ? WHERE singleton_id = 1",
                    (cash + net_proceeds,),
                )
                if new_qty == 0:
                    connection.execute(
                        "DELETE FROM positions WHERE symbol = ? AND product = ?",
                        (plan.symbol, plan.product.value),
                    )
                else:
                    connection.execute(
                        "UPDATE positions SET quantity = ? WHERE symbol = ? AND product = ?",
                        (new_qty, plan.symbol, plan.product.value),
                    )

            cursor = connection.execute(
                """
                INSERT INTO paper_orders(
                    intent_id, symbol, side, product, quantity, price, status,
                    filled_quantity, executed_at, realized_pnl,
                    reference_average_price, charges, charge_treatment
                ) VALUES (?, ?, ?, ?, ?, ?, 'FILLED', ?, ?, ?, ?, ?, ?)
                """,
                (
                    plan.intent_id,
                    plan.symbol,
                    plan.side.value,
                    plan.product.value,
                    plan.quantity,
                    price,
                    plan.quantity,
                    now.isoformat(),
                    realized_pnl,
                    original_avg if plan.side == Side.SELL else current_avg,
                    charges,
                    charge_treatment,
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
