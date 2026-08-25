from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

ThesisStatus = Literal["OPEN", "CLOSED", "INVALIDATED"]


@dataclass(frozen=True)
class Thesis:
    thesis_id: str
    symbol: str
    strategy_id: str
    created_at: datetime
    data_cutoff_at: datetime
    horizon: str
    thesis: str
    evidence_ids: tuple[str, ...]
    status: ThesisStatus = "OPEN"
    closed_at: datetime | None = None
    close_reason: str = ""


class ThesisStore:
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
                CREATE TABLE IF NOT EXISTS theses (
                    thesis_id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    strategy_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    data_cutoff_at TEXT NOT NULL,
                    horizon TEXT NOT NULL,
                    thesis TEXT NOT NULL,
                    evidence_ids_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    closed_at TEXT,
                    close_reason TEXT NOT NULL DEFAULT ''
                )
                """
            )

    @staticmethod
    def _validate(thesis: Thesis) -> None:
        if thesis.created_at.tzinfo is None or thesis.data_cutoff_at.tzinfo is None:
            raise ValueError("thesis timestamps must be timezone-aware")
        if thesis.data_cutoff_at > thesis.created_at:
            raise ValueError("thesis data cutoff cannot be after creation time")
        if not thesis.thesis_id or not thesis.symbol or not thesis.thesis:
            raise ValueError("thesis id, symbol and text are required")

    def create(self, thesis: Thesis) -> None:
        self._validate(thesis)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO theses(
                    thesis_id, symbol, strategy_id, created_at, data_cutoff_at,
                    horizon, thesis, evidence_ids_json, status, closed_at, close_reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    thesis.thesis_id,
                    thesis.symbol.upper(),
                    thesis.strategy_id,
                    thesis.created_at.isoformat(),
                    thesis.data_cutoff_at.isoformat(),
                    thesis.horizon,
                    thesis.thesis,
                    json.dumps(thesis.evidence_ids),
                    thesis.status,
                    thesis.closed_at.isoformat() if thesis.closed_at else None,
                    thesis.close_reason,
                ),
            )

    @staticmethod
    def _from_row(row: sqlite3.Row) -> Thesis:
        raw_status = str(row["status"])
        if raw_status not in {"OPEN", "CLOSED", "INVALIDATED"}:
            raise RuntimeError(f"invalid thesis status in database: {raw_status}")
        return Thesis(
            thesis_id=str(row["thesis_id"]),
            symbol=str(row["symbol"]),
            strategy_id=str(row["strategy_id"]),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            data_cutoff_at=datetime.fromisoformat(str(row["data_cutoff_at"])),
            horizon=str(row["horizon"]),
            thesis=str(row["thesis"]),
            evidence_ids=tuple(json.loads(str(row["evidence_ids_json"]))),
            status=raw_status,  # type: ignore[arg-type]
            closed_at=(
                datetime.fromisoformat(str(row["closed_at"]))
                if row["closed_at"] is not None
                else None
            ),
            close_reason=str(row["close_reason"]),
        )

    def get(self, thesis_id: str) -> Thesis | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM theses WHERE thesis_id = ?",
                (thesis_id,),
            ).fetchone()
        return self._from_row(row) if row is not None else None

    def open_for_symbol(self, symbol: str) -> list[Thesis]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM theses
                WHERE symbol = ? AND status = 'OPEN'
                ORDER BY created_at
                """,
                (symbol.upper(),),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def close(
        self,
        thesis_id: str,
        closed_at: datetime,
        reason: str,
        invalidated: bool = False,
    ) -> Thesis:
        if closed_at.tzinfo is None:
            raise ValueError("thesis close timestamp must be timezone-aware")
        if not reason.strip():
            raise ValueError("closing a thesis requires a reason")
        status: ThesisStatus = "INVALIDATED" if invalidated else "CLOSED"
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE theses
                SET status = ?, closed_at = ?, close_reason = ?
                WHERE thesis_id = ? AND status = 'OPEN'
                """,
                (status, closed_at.isoformat(), reason.strip(), thesis_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("thesis is missing or is no longer open")
        updated = self.get(thesis_id)
        if updated is None:
            raise RuntimeError("closed thesis disappeared")
        return updated
