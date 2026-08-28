from __future__ import annotations

from datetime import datetime, timedelta
from statistics import mean, pstdev

from app.autonomous_trader import AutonomousTrader
from app.config import Settings
from app.history_loader import NSEHistoryLoader
from app.models import Position, Quote
from app.scheduler import IST
from app.zerodha_api import ZerodhaApi


class ProductionAutonomousTrader(AutonomousTrader):
    """Production trader with optional full-NSE dynamic universe discovery.

    Paper and live modes use this same class. Execution mode is still selected by
    the existing broker boundary in ``AutonomousTrader``; universe selection,
    research, risk, scheduling and market data are shared.

    An empty ``TRADING_WATCHLIST`` enables dynamic mode. A non-empty watchlist is
    an explicit operator override and delegates to the established fixed-universe
    implementation.
    """

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self._nse_history = NSEHistoryLoader(self.data_dir / "nse-history")
        self._dynamic_ranked: tuple[str, ...] = ()
        self._last_candidate_bucket: int | None = None

    def _warm_history(self, api: ZerodhaApi, now: datetime) -> None:
        if not self.settings.dynamic_universe:
            super()._warm_history(api, now)
            return

        today = now.astimezone(IST).date().isoformat()
        if self._history_warmed_date == today:
            return
        end = now.astimezone(IST).date() - timedelta(days=1)
        start = end - timedelta(days=self.settings.universe_history_days)
        self.market_data, result = self._nse_history.load_range(
            start,
            end,
            store=self.market_data,
        )
        self._history_warmed_date = today
        self.state_store.set_history_warm(now.astimezone(IST).date())
        self._dynamic_ranked = self._rank_dynamic_universe(now)
        self.operations.append_event(
            "market_data",
            "DYNAMIC_NSE_UNIVERSE_WARMED",
            {
                "start": start.isoformat(),
                "end": end.isoformat(),
                "loaded_days": result.loaded_days,
                "missing_days": result.missing_days,
                "candles": result.candles,
                "symbols_with_history": len(self.market_data.symbols()),
                "eligible_symbols": len(self._dynamic_ranked),
                "shortlist": list(self._dynamic_ranked[: self.settings.universe_scan_limit]),
                "ranking": "momentum_breakout_volume_v2",
            },
            now,
        )

    @staticmethod
    def _clamp(value: float, lower: float, upper: float) -> float:
        return max(lower, min(upper, value))

    def _opportunity_score(self, history: list[object]) -> float:
        # ``history`` is a Candle list at runtime. Keeping this helper local to the
        # scanner avoids coupling the production selector to a second model type.
        candles = history
        if len(candles) < 2:
            return float("-inf")

        first = candles[0]
        last = candles[-1]
        long_return = (last.close / first.close) - 1 if first.close > 0 else 0.0

        short_anchor = candles[-6] if len(candles) >= 6 else first
        short_return = (
            (last.close / short_anchor.close) - 1 if short_anchor.close > 0 else 0.0
        )

        high = max(candle.high for candle in candles)
        near_high = (last.close / high) if high > 0 else 0.0

        avg_volume = mean(candle.volume for candle in candles) or 1.0
        recent = candles[-5:] if len(candles) >= 5 else candles
        recent_volume = mean(candle.volume for candle in recent)
        volume_ratio = recent_volume / avg_volume

        daily_returns = [
            (candles[index].close / candles[index - 1].close) - 1
            for index in range(1, len(candles))
            if candles[index - 1].close > 0
        ]
        volatility = pstdev(daily_returns) if len(daily_returns) >= 2 else 0.0

        # Liquidity is a hard eligibility gate, not the dominant rank signal.
        # This lets genuine movers compete with mega-caps instead of simply
        # sorting by traded rupees. Scores reward multi-horizon strength,
        # participation/volume acceleration and trading near recent highs while
        # mildly penalising extremely unstable names.
        return (
            0.45 * self._clamp(long_return, -0.50, 0.75)
            + 0.35 * self._clamp(short_return, -0.25, 0.35)
            + 0.12 * self._clamp(volume_ratio - 1.0, -0.75, 2.0)
            + 0.08 * self._clamp(near_high - 0.90, -0.30, 0.10)
            - 0.10 * max(0.0, volatility - 0.05)
        )

    def _rank_dynamic_universe(self, now: datetime) -> tuple[str, ...]:
        ranked: list[tuple[float, str]] = []
        for symbol in self.market_data.symbols():
            history = self.market_data.as_of(symbol, now, limit=20)
            if len(history) < self.settings.universe_min_history_bars:
                continue
            if min(candle.close for candle in history) < self.settings.universe_min_price:
                continue
            avg_traded_value = mean(candle.close * candle.volume for candle in history)
            if avg_traded_value < self.settings.universe_min_avg_traded_value:
                continue
            ranked.append((self._opportunity_score(history), symbol))
        ranked.sort(reverse=True)
        return tuple(symbol for _, symbol in ranked[: self.settings.universe_scan_limit])

    def _ranked_symbols(self, now: datetime) -> tuple[str, ...]:
        if not self.settings.dynamic_universe:
            return self.settings.watchlist
        if not self._dynamic_ranked:
            self._dynamic_ranked = self._rank_dynamic_universe(now)
        return self._dynamic_ranked

    def _active_dynamic_window(self, now: datetime) -> tuple[str, ...]:
        ranked = self._ranked_symbols(now)
        if not ranked:
            return ()
        window_size = min(self.settings.max_ai_candidates, len(ranked))
        if window_size >= len(ranked):
            return ranked

        bucket = int(now.timestamp()) // self.settings.decision_interval_seconds
        offset = (bucket * window_size) % len(ranked)
        end = offset + window_size
        if end <= len(ranked):
            selected = ranked[offset:end]
        else:
            selected = ranked[offset:] + ranked[: end - len(ranked)]

        if bucket != self._last_candidate_bucket:
            self._last_candidate_bucket = bucket
            self.operations.append_event(
                "research",
                "CANDIDATES_SELECTED",
                {
                    "symbols": list(selected),
                    "pool_size": len(ranked),
                    "window_size": window_size,
                    "rotation_offset": offset,
                    "ranking": "momentum_breakout_volume_v2",
                },
                now,
            )
        return selected

    def _quotes_for_portfolio(
        self,
        api: ZerodhaApi,
        positions: list[Position],
    ) -> dict[str, Quote]:
        if not self.settings.dynamic_universe:
            return super()._quotes_for_portfolio(api, positions)
        now = datetime.now(IST)
        selected = self._active_dynamic_window(now)
        held = self._portfolio_symbols(positions)
        symbols = tuple(dict.fromkeys((*held, *selected)))
        return api.quotes(symbols)

    def _candidates(
        self,
        positions: list[Position],
        now: datetime,
        *,
        allow_new_buys: bool,
    ) -> list[str]:
        if not self.settings.dynamic_universe:
            return super()._candidates(positions, now, allow_new_buys=allow_new_buys)
        held = list(dict.fromkeys(position.symbol for position in positions))
        if not allow_new_buys:
            return held
        held_set = set(held)
        selected = [
            symbol for symbol in self._active_dynamic_window(now) if symbol not in held_set
        ]
        return held + selected
