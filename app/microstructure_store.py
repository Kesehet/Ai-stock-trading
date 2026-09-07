from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from threading import Lock
from zoneinfo import ZoneInfo

from app.microstructure import BookLevel, BookTick

IST = ZoneInfo("Asia/Kolkata")


class KiteFullTickAdapter:
    """Convert Kite full-mode tick dictionaries into internal book snapshots.

    The adapter is intentionally read-only. It has no broker-order capability.
    """

    def __init__(self, symbols_by_token: Mapping[int, str]) -> None:
        self._symbols_by_token = dict(symbols_by_token)

    def from_tick(
        self,
        raw: Mapping[str, object],
        *,
        received_at: datetime | None = None,
    ) -> BookTick | None:
        token = _as_int(raw.get("instrument_token"))
        symbol = self._symbols_by_token.get(token)
        if symbol is None:
            return None

        depth = raw.get("depth")
        if not isinstance(depth, Mapping):
            return None
        bids = _parse_levels(depth.get("buy"))
        asks = _parse_levels(depth.get("sell"))
        if not bids or not asks:
            return None

        timestamp = _as_datetime(raw.get("exchange_timestamp"))
        if timestamp is None:
            timestamp = _as_datetime(raw.get("timestamp"))
        if timestamp is None:
            timestamp = received_at or datetime.now(tz=IST)
        elif timestamp.tzinfo is None:
            # Kite exchange timestamps are exchange-local wall-clock times.
            timestamp = timestamp.replace(tzinfo=IST)

        return BookTick(
            symbol=symbol,
            timestamp=timestamp,
            last_price=_as_float(raw.get("last_price")),
            last_quantity=_as_int(raw.get("last_quantity")),
            volume=_as_int(raw.get("volume")),
            bids=bids,
            asks=asks,
        )


class MicrostructureEventStore:
    """SQLite event store with bounded per-symbol retention for full-depth ticks."""

    def __init__(
        self,
        path: str | Path,
        *,
        max_events_per_symbol: int = 250_000,
        prune_every: int = 2_000,
    ) -> None:
        if max_events_per_symbol < 100:
            raise ValueError("max_events_per_symbol must be at least 100")
        if prune_every < 1:
            raise ValueError("prune_every must be positive")
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.max_events_per_symbol = max_events_per_symbol
        self.prune_every = prune_every
        self._lock = Lock()
        self._inserts = 0
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA synchronous=NORMAL")
        self._create_schema()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def __enter__(self) -> MicrostructureEventStore:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def record(self, tick: BookTick) -> int:
        bids_json = _levels_to_json(tick.bids)
        asks_json = _levels_to_json(tick.asks)
        with self._lock:
            cursor = self._connection.execute(
                """
                INSERT INTO microstructure_events (
                    symbol, event_timestamp, last_price, last_quantity, volume,
                    bids_json, asks_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tick.symbol,
                    tick.timestamp.isoformat(),
                    tick.last_price,
                    tick.last_quantity,
                    tick.volume,
                    bids_json,
                    asks_json,
                ),
            )
            self._connection.commit()
            event_id = cursor.lastrowid
            if event_id is None:
                raise RuntimeError("SQLite did not return a microstructure event id")
            self._inserts += 1
            if self._inserts % self.prune_every == 0:
                self._prune_symbol(tick.symbol)
            return event_id

    def record_many(self, ticks: Sequence[BookTick]) -> int:
        if not ticks:
            return 0
        rows = [
            (
                tick.symbol,
                tick.timestamp.isoformat(),
                tick.last_price,
                tick.last_quantity,
                tick.volume,
                _levels_to_json(tick.bids),
                _levels_to_json(tick.asks),
            )
            for tick in ticks
        ]
        with self._lock:
            self._connection.executemany(
                """
                INSERT INTO microstructure_events (
                    symbol, event_timestamp, last_price, last_quantity, volume,
                    bids_json, asks_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            self._connection.commit()
            self._inserts += len(rows)
            if self._inserts >= self.prune_every:
                for symbol in {tick.symbol for tick in ticks}:
                    self._prune_symbol(symbol)
                self._inserts %= self.prune_every
        return len(rows)

    def iter_ticks(
        self,
        *,
        symbol: str | None = None,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        limit: int | None = None,
    ) -> Iterator[BookTick]:
        clauses: list[str] = []
        values: list[object] = []
        if symbol is not None:
            clauses.append("symbol = ?")
            values.append(symbol.upper())
        if start_at is not None:
            clauses.append("event_timestamp >= ?")
            values.append(start_at.isoformat())
        if end_at is not None:
            clauses.append("event_timestamp <= ?")
            values.append(end_at.isoformat())
        query = (
            "SELECT symbol, event_timestamp, last_price, last_quantity, volume, "
            "bids_json, asks_json FROM microstructure_events"
        )
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY id ASC"
        if limit is not None:
            if limit < 1:
                return
            query += " LIMIT ?"
            values.append(limit)

        with self._lock:
            rows = list(self._connection.execute(query, values))
        for row in rows:
            yield BookTick(
                symbol=str(row[0]),
                timestamp=datetime.fromisoformat(str(row[1])),
                last_price=float(row[2]),
                last_quantity=int(row[3]),
                volume=int(row[4]),
                bids=_levels_from_json(str(row[5])),
                asks=_levels_from_json(str(row[6])),
            )

    def symbols(self) -> tuple[str, ...]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT DISTINCT symbol FROM microstructure_events ORDER BY symbol"
            ).fetchall()
        return tuple(str(row[0]) for row in rows)

    def count(self, *, symbol: str | None = None) -> int:
        with self._lock:
            if symbol is None:
                row = self._connection.execute(
                    "SELECT COUNT(*) FROM microstructure_events"
                ).fetchone()
            else:
                row = self._connection.execute(
                    "SELECT COUNT(*) FROM microstructure_events WHERE symbol = ?",
                    (symbol.upper(),),
                ).fetchone()
        return int(row[0]) if row is not None else 0

    def _create_schema(self) -> None:
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS microstructure_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                event_timestamp TEXT NOT NULL,
                last_price REAL NOT NULL,
                last_quantity INTEGER NOT NULL,
                volume INTEGER NOT NULL,
                bids_json TEXT NOT NULL,
                asks_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_microstructure_symbol_id
                ON microstructure_events(symbol, id);
            CREATE INDEX IF NOT EXISTS idx_microstructure_timestamp
                ON microstructure_events(event_timestamp);
            """
        )
        self._connection.commit()

    def _prune_symbol(self, symbol: str) -> None:
        self._connection.execute(
            """
            DELETE FROM microstructure_events
            WHERE symbol = ?
              AND id NOT IN (
                  SELECT id FROM microstructure_events
                  WHERE symbol = ?
                  ORDER BY id DESC
                  LIMIT ?
              )
            """,
            (symbol, symbol, self.max_events_per_symbol),
        )
        self._connection.commit()


def _parse_levels(value: object) -> tuple[BookLevel, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    result: list[BookLevel] = []
    for item in value[:5]:
        if not isinstance(item, Mapping):
            continue
        price = _as_float(item.get("price"))
        quantity = _as_int(item.get("quantity"))
        orders = _as_int(item.get("orders"))
        if price > 0:
            result.append(BookLevel(price=price, quantity=quantity, orders=orders))
    return tuple(result)


def _levels_to_json(levels: Sequence[BookLevel]) -> str:
    return json.dumps(
        [[level.price, level.quantity, level.orders] for level in levels[:5]],
        separators=(",", ":"),
    )


def _levels_from_json(payload: str) -> tuple[BookLevel, ...]:
    parsed = json.loads(payload)
    if not isinstance(parsed, list):
        return ()
    levels: list[BookLevel] = []
    for row in parsed[:5]:
        if not isinstance(row, list) or len(row) < 2:
            continue
        levels.append(
            BookLevel(
                price=_as_float(row[0]),
                quantity=_as_int(row[1]),
                orders=_as_int(row[2]) if len(row) > 2 else 0,
            )
        )
    return tuple(levels)


def _as_int(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float, str)):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return 0
    return 0


def _as_float(value: object) -> float:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float, str)):
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0
    return 0.0


def _as_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None
