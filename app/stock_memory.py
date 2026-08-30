from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class StockMemory:
    id: int | None
    symbol: str
    recorded_at: datetime
    action: str
    confidence: float
    target_allocation_pct: float
    horizon: str
    thesis: str
    manager_summary: str
    evidence_ids: tuple[str, ...]
    stop_price: float | None = None
    target_price: float | None = None

    def as_text(self) -> str:
        evidence = ",".join(self.evidence_ids) or "NONE"
        stop = f"{self.stop_price:.2f}" if self.stop_price is not None else "NA"
        target = f"{self.target_price:.2f}" if self.target_price is not None else "NA"
        return (
            f"recorded_at={self.recorded_at.isoformat()} action={self.action} "
            f"confidence={self.confidence:.2f} allocation={self.target_allocation_pct:.4f} "
            f"horizon={self.horizon} stop={stop} target={target} "
            f"thesis={self.thesis} manager_summary={self.manager_summary} "
            f"evidence_ids={evidence}"
        )


class StockMemoryStore:
    """Append-only durable memory of the fund's evolving strategy for each stock."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS stock_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    action TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    target_allocation_pct REAL NOT NULL,
                    horizon TEXT NOT NULL,
                    thesis TEXT NOT NULL,
                    manager_summary TEXT NOT NULL,
                    evidence_ids_json TEXT NOT NULL,
                    stop_price REAL,
                    target_price REAL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_stock_memory_symbol_time
                ON stock_memory(symbol, recorded_at DESC)
                """
            )

    @staticmethod
    def _validate(item: StockMemory) -> None:
        if item.recorded_at.tzinfo is None:
            raise ValueError("stock memory timestamp must be timezone-aware")
        if not item.symbol.strip() or not item.action.strip() or not item.thesis.strip():
            raise ValueError("symbol, action and thesis are required")
        if not 0 <= item.confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")
        if not 0 <= item.target_allocation_pct <= 1:
            raise ValueError("target allocation must be between 0 and 1")

    def append(self, item: StockMemory) -> int:
        self._validate(item)
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO stock_memory(
                    symbol, recorded_at, action, confidence, target_allocation_pct,
                    horizon, thesis, manager_summary, evidence_ids_json,
                    stop_price, target_price
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.symbol.upper(),
                    item.recorded_at.isoformat(),
                    item.action.upper(),
                    item.confidence,
                    item.target_allocation_pct,
                    item.horizon,
                    item.thesis,
                    item.manager_summary,
                    json.dumps(item.evidence_ids),
                    item.stop_price,
                    item.target_price,
                ),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("stock memory insert did not return an id")
            return int(cursor.lastrowid)

    @staticmethod
    def _from_row(row: sqlite3.Row) -> StockMemory:
        return StockMemory(
            id=int(row["id"]),
            symbol=str(row["symbol"]),
            recorded_at=datetime.fromisoformat(str(row["recorded_at"])),
            action=str(row["action"]),
            confidence=float(row["confidence"]),
            target_allocation_pct=float(row["target_allocation_pct"]),
            horizon=str(row["horizon"]),
            thesis=str(row["thesis"]),
            manager_summary=str(row["manager_summary"]),
            evidence_ids=tuple(json.loads(str(row["evidence_ids_json"]))),
            stop_price=(float(row["stop_price"]) if row["stop_price"] is not None else None),
            target_price=(
                float(row["target_price"]) if row["target_price"] is not None else None
            ),
        )

    def recent_for_symbol(self, symbol: str, limit: int = 8) -> list[StockMemory]:
        if limit <= 0:
            return []
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM stock_memory
                WHERE symbol = ?
                ORDER BY recorded_at DESC, id DESC
                LIMIT ?
                """,
                (symbol.upper(), limit),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def recent(self, limit: int = 200) -> list[StockMemory]:
        if limit <= 0:
            return []
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM stock_memory
                ORDER BY recorded_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._from_row(row) for row in rows]
