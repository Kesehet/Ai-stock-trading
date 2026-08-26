from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.models import Product


@dataclass(frozen=True)
class PositionPolicy:
    symbol: str
    product: Product
    stop_price: float | None
    target_price: float | None
    thesis_id: str
    updated_at: datetime


class PositionPolicyStore:
    """Persistent stop/target policies for bot-managed positions."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS position_policies (
                    symbol TEXT NOT NULL,
                    product TEXT NOT NULL,
                    stop_price REAL,
                    target_price REAL,
                    thesis_id TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(symbol, product)
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    @staticmethod
    def _from_row(row: sqlite3.Row) -> PositionPolicy:
        return PositionPolicy(
            symbol=str(row["symbol"]),
            product=Product(str(row["product"])),
            stop_price=(float(row["stop_price"]) if row["stop_price"] is not None else None),
            target_price=(
                float(row["target_price"]) if row["target_price"] is not None else None
            ),
            thesis_id=str(row["thesis_id"]),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )

    def set(
        self,
        *,
        symbol: str,
        product: Product,
        stop_price: float | None,
        target_price: float | None,
        thesis_id: str,
    ) -> PositionPolicy:
        if stop_price is not None and stop_price <= 0:
            raise ValueError("stop_price must be positive")
        if target_price is not None and target_price <= 0:
            raise ValueError("target_price must be positive")
        updated_at = datetime.now(UTC)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO position_policies(
                    symbol, product, stop_price, target_price, thesis_id, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, product) DO UPDATE SET
                    stop_price=excluded.stop_price,
                    target_price=excluded.target_price,
                    thesis_id=excluded.thesis_id,
                    updated_at=excluded.updated_at
                """,
                (
                    symbol.upper(),
                    product.value,
                    stop_price,
                    target_price,
                    thesis_id,
                    updated_at.isoformat(),
                ),
            )
        return PositionPolicy(
            symbol=symbol.upper(),
            product=product,
            stop_price=stop_price,
            target_price=target_price,
            thesis_id=thesis_id,
            updated_at=updated_at,
        )

    def get(self, symbol: str, product: Product) -> PositionPolicy | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT symbol, product, stop_price, target_price, thesis_id, updated_at
                FROM position_policies
                WHERE symbol = ? AND product = ?
                """,
                (symbol.upper(), product.value),
            ).fetchone()
        return self._from_row(row) if row is not None else None

    def all(self) -> list[PositionPolicy]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT symbol, product, stop_price, target_price, thesis_id, updated_at
                FROM position_policies
                ORDER BY symbol, product
                """
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def clear(self, symbol: str, product: Product) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM position_policies WHERE symbol = ? AND product = ?",
                (symbol.upper(), product.value),
            )
