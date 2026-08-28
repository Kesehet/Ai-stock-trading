from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from statistics import mean

from app.market_data import Candle, HistoricalDataStore
from app.scheduler import IST
from app.zerodha_api import LiveMarketSnapshot


@dataclass(frozen=True)
class IntradayOpportunity:
    symbol: str
    score: float
    move_pct: float
    gap_pct: float
    breakout_pct: float
    volume_pace: float
    intraday_position: float
    acceleration_pct: float


class IntradayOpportunityScanner:
    """Deterministic live NSE scanner used to promote hot names to AI research."""

    _OPEN = time(9, 15)
    _CLOSE = time(15, 30)

    def __init__(self, market_data: HistoricalDataStore) -> None:
        self.market_data = market_data
        self._previous: dict[str, LiveMarketSnapshot] = {}

    @classmethod
    def _session_fraction(cls, now: datetime) -> float:
        local = now.astimezone(IST)
        session_start = local.replace(
            hour=cls._OPEN.hour,
            minute=cls._OPEN.minute,
            second=0,
            microsecond=0,
        )
        session_end = local.replace(
            hour=cls._CLOSE.hour,
            minute=cls._CLOSE.minute,
            second=0,
            microsecond=0,
        )
        total = max((session_end - session_start).total_seconds(), 1.0)
        elapsed = (local - session_start).total_seconds()
        return max(0.05, min(1.0, elapsed / total))

    @staticmethod
    def _clamp(value: float, low: float, high: float) -> float:
        return max(low, min(high, value))

    def _history(self, symbol: str, now: datetime) -> list[Candle]:
        return self.market_data.as_of(symbol, now, limit=20)

    def _score_one(
        self,
        snapshot: LiveMarketSnapshot,
        now: datetime,
    ) -> IntradayOpportunity | None:
        history = self._history(snapshot.symbol, now)
        if len(history) < 5:
            return None

        previous_close = snapshot.previous_close
        if previous_close <= 0 or snapshot.last_price <= 0:
            return None

        move = (snapshot.last_price / previous_close) - 1.0
        gap = (snapshot.open_price / previous_close) - 1.0
        recent_high = max(candle.high for candle in history)
        breakout = (snapshot.last_price / recent_high) - 1.0 if recent_high > 0 else 0.0

        avg_daily_volume = mean(candle.volume for candle in history) or 1.0
        expected_volume = avg_daily_volume * self._session_fraction(now)
        volume_pace = snapshot.volume / expected_volume if expected_volume > 0 else 0.0

        day_range = snapshot.high_price - snapshot.low_price
        intraday_position = (
            (snapshot.last_price - snapshot.low_price) / day_range
            if day_range > 0
            else 0.5
        )

        previous = self._previous.get(snapshot.symbol)
        acceleration = 0.0
        if previous is not None and previous.last_price > 0:
            acceleration = (snapshot.last_price / previous.last_price) - 1.0

        # The scanner rewards several distinct ways a stock can become interesting
        # right now: a large move, abnormal participation, a fresh breakout,
        # holding near the intraday high, or accelerating between scans. Gap-only
        # names get little credit unless buyers keep following through.
        score = (
            0.34 * self._clamp(move, -0.08, 0.12)
            + 0.16 * self._clamp(gap, -0.06, 0.08)
            + 0.20 * self._clamp(breakout, -0.04, 0.08)
            + 0.16 * self._clamp(volume_pace - 1.0, -1.0, 4.0) / 4.0
            + 0.08 * self._clamp(intraday_position - 0.5, -0.5, 0.5)
            + 0.24 * self._clamp(acceleration, -0.03, 0.04)
        )

        return IntradayOpportunity(
            symbol=snapshot.symbol,
            score=score,
            move_pct=move,
            gap_pct=gap,
            breakout_pct=breakout,
            volume_pace=volume_pace,
            intraday_position=intraday_position,
            acceleration_pct=acceleration,
        )

    def rank(
        self,
        snapshots: dict[str, LiveMarketSnapshot],
        now: datetime,
    ) -> list[IntradayOpportunity]:
        opportunities = [
            opportunity
            for snapshot in snapshots.values()
            if (opportunity := self._score_one(snapshot, now)) is not None
        ]
        self._previous.update(snapshots)
        opportunities.sort(key=lambda item: (item.score, item.move_pct), reverse=True)
        return opportunities
