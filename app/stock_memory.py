from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path


THESIS_DRIFT_WINDOW = timedelta(minutes=15)


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


@dataclass(frozen=True)
class ThesisDriftRecord:
    id: int
    symbol: str
    previous_memory_id: int
    current_memory_id: int
    previous_recorded_at: datetime
    current_recorded_at: datetime
    previous_action: str
    current_action: str
    elapsed_seconds: float
    previous_confidence: float
    current_confidence: float
    confidence_delta: float
    previous_target_allocation_pct: float
    current_target_allocation_pct: float
    allocation_delta: float
    added_evidence_ids: tuple[str, ...]
    removed_evidence_ids: tuple[str, ...]
    previous_thesis: str
    current_thesis: str

    def as_payload(self) -> dict[str, object]:
        return {
            "id": self.id,
            "symbol": self.symbol,
            "previous_memory_id": self.previous_memory_id,
            "current_memory_id": self.current_memory_id,
            "previous_recorded_at": self.previous_recorded_at.isoformat(),
            "current_recorded_at": self.current_recorded_at.isoformat(),
            "previous_action": self.previous_action,
            "current_action": self.current_action,
            "elapsed_seconds": round(self.elapsed_seconds, 1),
            "previous_confidence": self.previous_confidence,
            "current_confidence": self.current_confidence,
            "confidence_delta": round(self.confidence_delta, 4),
            "previous_target_allocation_pct": self.previous_target_allocation_pct,
            "current_target_allocation_pct": self.current_target_allocation_pct,
            "allocation_delta": round(self.allocation_delta, 4),
            "added_evidence_ids": list(self.added_evidence_ids),
            "removed_evidence_ids": list(self.removed_evidence_ids),
            "new_evidence_count": len(self.added_evidence_ids),
            "previous_thesis": self.previous_thesis,
            "current_thesis": self.current_thesis,
            "diagnostic_only": True,
        }


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
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS thesis_drift (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    previous_memory_id INTEGER NOT NULL,
                    current_memory_id INTEGER NOT NULL,
                    previous_recorded_at TEXT NOT NULL,
                    current_recorded_at TEXT NOT NULL,
                    previous_action TEXT NOT NULL,
                    current_action TEXT NOT NULL,
                    elapsed_seconds REAL NOT NULL,
                    previous_confidence REAL NOT NULL,
                    current_confidence REAL NOT NULL,
                    confidence_delta REAL NOT NULL,
                    previous_target_allocation_pct REAL NOT NULL,
                    current_target_allocation_pct REAL NOT NULL,
                    allocation_delta REAL NOT NULL,
                    added_evidence_ids_json TEXT NOT NULL,
                    removed_evidence_ids_json TEXT NOT NULL,
                    previous_thesis TEXT NOT NULL,
                    current_thesis TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_thesis_drift_symbol_time
                ON thesis_drift(symbol, current_recorded_at DESC)
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
        symbol = item.symbol.upper()
        action = item.action.upper()
        with self._connect() as connection:
            previous_row = connection.execute(
                """
                SELECT * FROM stock_memory
                WHERE symbol = ?
                ORDER BY recorded_at DESC, id DESC
                LIMIT 1
                """,
                (symbol,),
            ).fetchone()
            cursor = connection.execute(
                """
                INSERT INTO stock_memory(
                    symbol, recorded_at, action, confidence, target_allocation_pct,
                    horizon, thesis, manager_summary, evidence_ids_json,
                    stop_price, target_price
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    symbol,
                    item.recorded_at.isoformat(),
                    action,
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
            current_id = int(cursor.lastrowid)
            if previous_row is not None:
                self._record_drift_if_needed(
                    connection=connection,
                    previous=self._from_row(previous_row),
                    current=item,
                    current_id=current_id,
                )
            return current_id

    @staticmethod
    def _record_drift_if_needed(
        *,
        connection: sqlite3.Connection,
        previous: StockMemory,
        current: StockMemory,
        current_id: int,
    ) -> None:
        previous_action = previous.action.upper()
        current_action = current.action.upper()
        if previous_action == current_action or previous.id is None:
            return
        elapsed = (current.recorded_at - previous.recorded_at).total_seconds()
        if elapsed < 0 or elapsed > THESIS_DRIFT_WINDOW.total_seconds():
            return
        previous_ids = set(previous.evidence_ids)
        current_ids = set(current.evidence_ids)
        added_ids = tuple(sorted(current_ids - previous_ids))
        removed_ids = tuple(sorted(previous_ids - current_ids))
        connection.execute(
            """
            INSERT INTO thesis_drift(
                symbol, previous_memory_id, current_memory_id,
                previous_recorded_at, current_recorded_at,
                previous_action, current_action, elapsed_seconds,
                previous_confidence, current_confidence, confidence_delta,
                previous_target_allocation_pct, current_target_allocation_pct,
                allocation_delta, added_evidence_ids_json, removed_evidence_ids_json,
                previous_thesis, current_thesis
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                current.symbol.upper(),
                previous.id,
                current_id,
                previous.recorded_at.isoformat(),
                current.recorded_at.isoformat(),
                previous_action,
                current_action,
                elapsed,
                previous.confidence,
                current.confidence,
                current.confidence - previous.confidence,
                previous.target_allocation_pct,
                current.target_allocation_pct,
                current.target_allocation_pct - previous.target_allocation_pct,
                json.dumps(added_ids),
                json.dumps(removed_ids),
                previous.thesis,
                current.thesis,
            ),
        )

    @staticmethod
    def _from_row(row: sqlite3.Row) -> StockMemory:
        raw_evidence = json.loads(str(row["evidence_ids_json"]))
        evidence_ids = (
            tuple(str(item) for item in raw_evidence)
            if isinstance(raw_evidence, list)
            else ()
        )
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
            evidence_ids=evidence_ids,
            stop_price=(float(row["stop_price"]) if row["stop_price"] is not None else None),
            target_price=(
                float(row["target_price"]) if row["target_price"] is not None else None
            ),
        )

    @staticmethod
    def _drift_from_row(row: sqlite3.Row) -> ThesisDriftRecord:
        raw_added = json.loads(str(row["added_evidence_ids_json"]))
        raw_removed = json.loads(str(row["removed_evidence_ids_json"]))
        return ThesisDriftRecord(
            id=int(row["id"]),
            symbol=str(row["symbol"]),
            previous_memory_id=int(row["previous_memory_id"]),
            current_memory_id=int(row["current_memory_id"]),
            previous_recorded_at=datetime.fromisoformat(str(row["previous_recorded_at"])),
            current_recorded_at=datetime.fromisoformat(str(row["current_recorded_at"])),
            previous_action=str(row["previous_action"]),
            current_action=str(row["current_action"]),
            elapsed_seconds=float(row["elapsed_seconds"]),
            previous_confidence=float(row["previous_confidence"]),
            current_confidence=float(row["current_confidence"]),
            confidence_delta=float(row["confidence_delta"]),
            previous_target_allocation_pct=float(
                row["previous_target_allocation_pct"]
            ),
            current_target_allocation_pct=float(row["current_target_allocation_pct"]),
            allocation_delta=float(row["allocation_delta"]),
            added_evidence_ids=tuple(str(item) for item in raw_added),
            removed_evidence_ids=tuple(str(item) for item in raw_removed),
            previous_thesis=str(row["previous_thesis"]),
            current_thesis=str(row["current_thesis"]),
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

    def recent_drift(self, limit: int = 100) -> list[ThesisDriftRecord]:
        if limit <= 0:
            return []
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM thesis_drift
                ORDER BY current_recorded_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._drift_from_row(row) for row in rows]
