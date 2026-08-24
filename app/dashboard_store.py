from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class PortfolioSnapshot:
    captured_at: datetime
    cash: float
    deployed: float
    holdings_value: float
    total_value: float


class DashboardSnapshotStore:
    """Small append-only NAV history used by the read-only dashboard."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS portfolio_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    captured_at TEXT NOT NULL,
                    cash REAL NOT NULL,
                    deployed REAL NOT NULL,
                    holdings_value REAL NOT NULL,
                    total_value REAL NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def append(self, snapshot: PortfolioSnapshot) -> None:
        if snapshot.captured_at.tzinfo is None:
            raise ValueError("snapshot timestamp must be timezone-aware")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO portfolio_snapshots(
                    captured_at, cash, deployed, holdings_value, total_value
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    snapshot.captured_at.isoformat(),
                    snapshot.cash,
                    snapshot.deployed,
                    snapshot.holdings_value,
                    snapshot.total_value,
                ),
            )

    def latest(self) -> PortfolioSnapshot | None:
        values = self.history(limit=1)
        return values[-1] if values else None

    def history(self, limit: int = 120) -> list[PortfolioSnapshot]:
        if limit <= 0:
            return []
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT captured_at, cash, deployed, holdings_value, total_value
                FROM portfolio_snapshots
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            PortfolioSnapshot(
                captured_at=datetime.fromisoformat(str(row["captured_at"])),
                cash=float(row["cash"]),
                deployed=float(row["deployed"]),
                holdings_value=float(row["holdings_value"]),
                total_value=float(row["total_value"]),
            )
            for row in reversed(rows)
        ]
