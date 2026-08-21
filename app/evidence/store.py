from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import cast

from app.evidence.models import EvidenceItem


class EvidenceStore:
    """SQLite-backed append-only evidence store with fingerprint deduplication."""

    def __init__(self, path: str | Path = "evidence.db") -> None:
        self.path = str(path)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS evidence (
                    id TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL UNIQUE,
                    symbol TEXT,
                    available_at TEXT NOT NULL,
                    published_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_evidence_available ON evidence(available_at)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_evidence_symbol ON evidence(symbol)"
            )

    def put(self, item: EvidenceItem) -> bool:
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO evidence(
                        id, fingerprint, symbol, available_at, published_at, payload
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item.id,
                        item.fingerprint,
                        item.symbol,
                        item.available_at.isoformat(),
                        item.published_at.isoformat(),
                        item.model_dump_json(),
                    ),
                )
        except sqlite3.IntegrityError:
            return False
        return True

    def put_many(self, items: list[EvidenceItem]) -> int:
        return sum(1 for item in items if self.put(item))

    def list_as_of(
        self,
        cutoff: datetime,
        symbol: str | None = None,
        limit: int = 100,
    ) -> list[EvidenceItem]:
        if limit <= 0:
            return []
        query = "SELECT payload FROM evidence WHERE available_at <= ?"
        params: list[object] = [cutoff.isoformat()]
        if symbol is not None:
            query += " AND symbol = ?"
            params.append(symbol)
        query += " ORDER BY available_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [
            EvidenceItem.model_validate_json(cast(str, row["payload"]))
            for row in rows
        ]
