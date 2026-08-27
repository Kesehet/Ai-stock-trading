from __future__ import annotations

from datetime import datetime, timedelta
from statistics import mean

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
            },
            now,
        )

    def _rank_dynamic_universe(self, now: datetime) -> tuple[str, ...]:
        ranked: list[tuple[float, str]] = []
        for symbol in self.market_data.symbols():
            history = self.market_data.as_of(symbol, now, limit=20)
            if len(history) < self.settings.universe_min_history_bars:
                continue
            last = history[-1]
            if last.close < self.settings.universe_min_price:
                continue
            avg_traded_value = mean(candle.close * candle.volume for candle in history)
            if avg_traded_value < self.settings.universe_min_avg_traded_value:
                continue
            first = history[0].close
            momentum = (last.close / first) - 1 if first > 0 else 0.0
            bounded_momentum = max(-0.5, min(0.5, momentum))
            score = avg_traded_value * (1.0 + bounded_momentum)
            ranked.append((score, symbol))
        ranked.sort(reverse=True)
        return tuple(symbol for _, symbol in ranked[: self.settings.universe_scan_limit])

    def _ranked_symbols(self, now: datetime) -> tuple[str, ...]:
        if not self.settings.dynamic_universe:
            return self.settings.watchlist
        if not self._dynamic_ranked:
            self._dynamic_ranked = self._rank_dynamic_universe(now)
        return self._dynamic_ranked

    def _quotes_for_portfolio(
        self,
        api: ZerodhaApi,
        positions: list[Position],
    ) -> dict[str, Quote]:
        if not self.settings.dynamic_universe:
            return super()._quotes_for_portfolio(api, positions)
        ranked = self._ranked_symbols(datetime.now(IST))
        held = self._portfolio_symbols(positions)
        symbols = tuple(
            dict.fromkeys((*held, *ranked[: self.settings.max_ai_candidates]))
        )
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
        ranked = [symbol for symbol in self._ranked_symbols(now) if symbol not in held_set]
        return held + ranked[: self.settings.max_ai_candidates]
