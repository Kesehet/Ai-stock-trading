from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SafetyState:
    safe_mode: bool
    reason: str
    updated_at: datetime


class OperationsStore:
    """Durable operational audit trail and safety state.

    This store must never receive raw broker secrets or access tokens.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    category TEXT NOT NULL,
                    action TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS safety_state (
                    singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
                    safe_mode INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )

    def append_event(
        self,
        category: str,
        action: str,
        payload: dict[str, Any] | None = None,
        created_at: datetime | None = None,
    ) -> int:
        timestamp = created_at or datetime.now(UTC)
        if timestamp.tzinfo is None:
            raise ValueError("audit event timestamp must be timezone-aware")
        serialized = json.dumps(payload or {}, sort_keys=True, separators=(",", ":"))
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO audit_events (created_at, category, action, payload_json)
                VALUES (?, ?, ?, ?)
                """,
                (timestamp.isoformat(), category, action, serialized),
            )
            event_id = cursor.lastrowid
        if event_id is None:
            raise RuntimeError("audit event insert did not return an id")
        return int(event_id)

    def set_safe_mode(
        self,
        enabled: bool,
        reason: str,
        updated_at: datetime | None = None,
    ) -> SafetyState:
        timestamp = updated_at or datetime.now(UTC)
        if timestamp.tzinfo is None:
            raise ValueError("safety state timestamp must be timezone-aware")
        if enabled and not reason.strip():
            raise ValueError("safe mode requires a reason")
        normalized_reason = reason.strip() if enabled else ""
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO safety_state (singleton_id, safe_mode, reason, updated_at)
                VALUES (1, ?, ?, ?)
                ON CONFLICT(singleton_id) DO UPDATE SET
                    safe_mode=excluded.safe_mode,
                    reason=excluded.reason,
                    updated_at=excluded.updated_at
                """,
                (1 if enabled else 0, normalized_reason, timestamp.isoformat()),
            )
        self.append_event(
            "safety",
            "SAFE_MODE_ENABLED" if enabled else "SAFE_MODE_CLEARED",
            {"reason": normalized_reason},
            timestamp,
        )
        return SafetyState(enabled, normalized_reason, timestamp)

    def get_safety_state(self) -> SafetyState:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT safe_mode, reason, updated_at
                FROM safety_state
                WHERE singleton_id = 1
                """
            ).fetchone()
        if row is None:
            return SafetyState(False, "", datetime.fromtimestamp(0, tz=UTC))
        return SafetyState(
            safe_mode=bool(row[0]),
            reason=str(row[1]),
            updated_at=datetime.fromisoformat(str(row[2])),
        )

    def recent_events(self, limit: int = 100) -> list[dict[str, Any]]:
        if limit < 1 or limit > 10_000:
            raise ValueError("limit must be between 1 and 10000")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, created_at, category, action, payload_json
                FROM audit_events
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            {
                "id": int(row[0]),
                "created_at": str(row[1]),
                "category": str(row[2]),
                "action": str(row[3]),
                "payload": json.loads(str(row[4])),
            }
            for row in rows
        ]
