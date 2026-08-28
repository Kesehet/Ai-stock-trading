from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path
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
    _HISTORY_SYMBOLS = 20
    _HISTORY_POINTS_PER_SYMBOL = 240

    def __init__(
        self,
        market_data: HistoricalDataStore,
        state_path: str | Path | None = None,
    ) -> None:
        self.market_data = market_data
        self.state_path = Path(state_path) if state_path is not None else None
        payload = self._load_state()
        self._previous_prices = self._load_previous_prices(payload)
        self._opportunity_history = self._load_opportunity_history(payload)

    def _load_state(self) -> dict[str, object]:
        if self.state_path is None or not self.state_path.exists():
            return {}
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _load_previous_prices(payload: dict[str, object]) -> dict[str, float]:
        prices = payload.get("previous_prices")
        if not isinstance(prices, dict):
            return {}
        result: dict[str, float] = {}
        for symbol, value in prices.items():
            if not isinstance(symbol, str):
                continue
            try:
                price = float(value)
            except (TypeError, ValueError):
                continue
            if price > 0:
                result[symbol.upper()] = price
        return result

    @staticmethod
    def _load_opportunity_history(
        payload: dict[str, object],
    ) -> dict[str, list[dict[str, object]]]:
        raw = payload.get("opportunity_history")
        if not isinstance(raw, dict):
            return {}
        result: dict[str, list[dict[str, object]]] = {}
        for symbol, items in raw.items():
            if not isinstance(symbol, str) or not isinstance(items, list):
                continue
            clean = [item for item in items if isinstance(item, dict)]
            if clean:
                result[symbol.upper()] = clean[-240:]
        return result

    def _save_state(self, now: datetime) -> None:
        if self.state_path is None:
            return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(f"{self.state_path.suffix}.tmp")
        payload = {
            "updated_at": now.astimezone(IST).isoformat(),
            "previous_prices": self._previous_prices,
            "opportunity_history": self._opportunity_history,
        }
        try:
            temporary.write_text(
                json.dumps(payload, separators=(",", ":"), sort_keys=True),
                encoding="utf-8",
            )
            temporary.replace(self.state_path)
        except OSError:
            temporary.unlink(missing_ok=True)

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

        previous_price = self._previous_prices.get(snapshot.symbol.upper())
        acceleration = 0.0
        if previous_price is not None and previous_price > 0:
            acceleration = (snapshot.last_price / previous_price) - 1.0

        # Reward genuine participation and momentum, but distinguish an interesting
        # stock from an attractive entry. Very extended breakouts near the session
        # high are still visible to research, just ranked below fresher setups.
        extension_penalty = (
            0.10 * self._clamp((move - 0.10) / 0.10, 0.0, 1.0)
            + 0.06 * self._clamp((breakout - 0.06) / 0.08, 0.0, 1.0)
            + 0.04 * self._clamp((intraday_position - 0.90) / 0.10, 0.0, 1.0)
        )
        score = (
            0.34 * self._clamp(move, -0.08, 0.12)
            + 0.16 * self._clamp(gap, -0.06, 0.08)
            + 0.20 * self._clamp(breakout, -0.04, 0.08)
            + 0.16 * self._clamp(volume_pace - 1.0, -1.0, 4.0) / 4.0
            + 0.08 * self._clamp(intraday_position - 0.5, -0.5, 0.5)
            + 0.24 * self._clamp(acceleration, -0.03, 0.04)
            - extension_penalty
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

    def _record_history(
        self,
        opportunities: list[IntradayOpportunity],
        snapshots: dict[str, LiveMarketSnapshot],
        now: datetime,
    ) -> None:
        local_date = now.astimezone(IST).date().isoformat()
        for symbol in list(self._opportunity_history):
            points = self._opportunity_history[symbol]
            recent = [
                point
                for point in points
                if str(point.get("session_date") or "") == local_date
            ]
            if recent:
                self._opportunity_history[symbol] = recent[-self._HISTORY_POINTS_PER_SYMBOL :]
            else:
                self._opportunity_history.pop(symbol, None)

        for item in opportunities[: self._HISTORY_SYMBOLS]:
            symbol = item.symbol.upper()
            snapshot = snapshots.get(item.symbol) or snapshots.get(symbol)
            if snapshot is None or snapshot.last_price <= 0:
                continue
            points = self._opportunity_history.setdefault(symbol, [])
            points.append(
                {
                    "at": now.astimezone(IST).isoformat(),
                    "session_date": local_date,
                    "price": snapshot.last_price,
                    "score": item.score,
                    "move_pct": item.move_pct,
                    "gap_pct": item.gap_pct,
                    "breakout_pct": item.breakout_pct,
                    "volume_pace": item.volume_pace,
                    "intraday_position": item.intraday_position,
                    "acceleration_pct": item.acceleration_pct,
                }
            )
            self._opportunity_history[symbol] = points[-self._HISTORY_POINTS_PER_SYMBOL :]

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
        opportunities.sort(key=lambda item: (item.score, item.move_pct), reverse=True)
        self._record_history(opportunities, snapshots, now)
        self._previous_prices.update(
            {
                symbol.upper(): snapshot.last_price
                for symbol, snapshot in snapshots.items()
                if snapshot.last_price > 0
            }
        )
        self._save_state(now)
        return opportunities
