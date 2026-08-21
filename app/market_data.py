from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Candle:
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None:
            raise ValueError("candle timestamp must be timezone-aware")
        if min(self.open, self.high, self.low, self.close) <= 0:
            raise ValueError("OHLC values must be positive")
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("high is inconsistent with OHLC values")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("low is inconsistent with OHLC values")
        if self.volume < 0:
            raise ValueError("volume cannot be negative")


class HistoricalDataStore:
    """Point-in-time candle repository for deterministic backtests."""

    def __init__(self, candles: Iterable[Candle] = ()) -> None:
        self._candles: dict[str, list[Candle]] = {}
        for candle in candles:
            self.add(candle)

    def add(self, candle: Candle) -> None:
        series = self._candles.setdefault(candle.symbol.upper(), [])
        series.append(candle)
        series.sort(key=lambda value: value.timestamp)

    def symbols(self) -> list[str]:
        return sorted(self._candles)

    def between(self, symbol: str, start: datetime, end: datetime) -> list[Candle]:
        return [
            candle
            for candle in self._candles.get(symbol.upper(), [])
            if start <= candle.timestamp <= end
        ]

    def as_of(self, symbol: str, cutoff: datetime, limit: int | None = None) -> list[Candle]:
        values = [
            candle
            for candle in self._candles.get(symbol.upper(), [])
            if candle.timestamp <= cutoff
        ]
        if limit is not None:
            if limit <= 0:
                return []
            return values[-limit:]
        return values

    def latest_as_of(self, symbol: str, cutoff: datetime) -> Candle | None:
        values = self.as_of(symbol, cutoff, limit=1)
        return values[0] if values else None
