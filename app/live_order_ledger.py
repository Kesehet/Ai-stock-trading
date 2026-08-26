from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True)
class LiveOrderRecord:
    intent_id: str
    broker_order_id: str
    status: str
    created_at: datetime
    updated_at: datetime


class LiveOrderLedger:
    """Fail-closed idempotency ledger for real broker placements."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS live_orders (
                    intent_id TEXT PRIMARY KEY,
                    broker_order_id TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def claim(self, intent_id: str) -> bool:
        now = datetime.now(UTC).isoformat()
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO live_orders(intent_id, status, created_at, updated_at)
                    VALUES (?, 'PENDING_SEND', ?, ?)
                    """,
                    (intent_id, now, now),
                )
        except sqlite3.IntegrityError:
            return False
        return True

    def update(self, intent_id: str, *, broker_order_id: str = "", status: str) -> None:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE live_orders
                SET broker_order_id = CASE WHEN ? = '' THEN broker_order_id ELSE ? END,
                    status = ?, updated_at = ?
                WHERE intent_id = ?
                """,
                (
                    broker_order_id,
                    broker_order_id,
                    status,
                    datetime.now(UTC).isoformat(),
                    intent_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError("live intent is not registered")

    def pending(self) -> list[LiveOrderRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT intent_id, broker_order_id, status, created_at, updated_at
                FROM live_orders
                WHERE status IN ('PENDING_SEND', 'UNKNOWN', 'SUBMITTED', 'OPEN', 'TRIGGER PENDING')
                ORDER BY created_at
                """
            ).fetchall()
        return [
            LiveOrderRecord(
                intent_id=str(row["intent_id"]),
                broker_order_id=str(row["broker_order_id"]),
                status=str(row["status"]),
                created_at=datetime.fromisoformat(str(row["created_at"])),
                updated_at=datetime.fromisoformat(str(row["updated_at"])),
            )
            for row in rows
        ]
