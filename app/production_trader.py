from __future__ import annotations

from datetime import datetime, timedelta
from statistics import mean, pstdev
from threading import Lock

from app.autonomous_trader import AutonomousTrader
from app.config import Settings
from app.history_loader import NSEHistoryLoader
from app.intraday_scanner import IntradayOpportunity, IntradayOpportunityScanner
from app.market_data import Candle
from app.models import Position, Quote
from app.scheduler import IST, MarketPhase
from app.zerodha_api import LiveMarketSnapshot, ZerodhaApi


class ProductionAutonomousTrader(AutonomousTrader):
    """Production trader with full-NSE discovery plus live opportunity scanning."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self._nse_history = NSEHistoryLoader(self.data_dir / "nse-history")
        self._dynamic_ranked: tuple[str, ...] = ()
        self._last_candidate_bucket: int | None = None
        self._intraday_scanner = IntradayOpportunityScanner(
            self.market_data,
            self.data_dir / "intraday-scanner-state.json",
        )
        self._last_intraday_scan: datetime | None = None
        self._intraday_hot: tuple[str, ...] = ()
        self._intraday_snapshots: dict[str, LiveMarketSnapshot] = {}
        self._intraday_state_lock = Lock()

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
        self._intraday_scanner = IntradayOpportunityScanner(
            self.market_data,
            self.data_dir / "intraday-scanner-state.json",
        )
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
                "shortlist": list(
                    self._dynamic_ranked[: self.settings.universe_scan_limit]
                ),
                "intraday_scan_pool": min(
                    len(self._dynamic_ranked),
                    self.settings.intraday_scan_pool_limit,
                ),
                "ranking": "momentum_breakout_volume_v2+live_intraday_v2",
            },
            now,
        )

    @staticmethod
    def _clamp(value: float, lower: float, upper: float) -> float:
        return max(lower, min(upper, value))

    def _opportunity_score(self, candles: list[Candle]) -> float:
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
        pool_limit = max(
            self.settings.universe_scan_limit,
            self.settings.intraday_scan_pool_limit,
        )
        return tuple(symbol for _, symbol in ranked[:pool_limit])

    def _ranked_symbols(self, now: datetime) -> tuple[str, ...]:
        if not self.settings.dynamic_universe:
            return self.settings.watchlist
        if not self._dynamic_ranked:
            self._dynamic_ranked = self._rank_dynamic_universe(now)
        return self._dynamic_ranked[: self.settings.universe_scan_limit]

    def _active_dynamic_window(self, now: datetime) -> tuple[str, ...]:
        ranked = self._ranked_symbols(now)
        if not ranked:
            return ()
        window_size = min(self.settings.max_ai_candidates, len(ranked))
        if window_size >= len(ranked):
            selected = ranked
            offset = 0
        else:
            bucket = int(now.timestamp()) // self.settings.decision_interval_seconds
            offset = (bucket * window_size) % len(ranked)
            end = offset + window_size
            if end <= len(ranked):
                selected = ranked[offset:end]
            else:
                selected = ranked[offset:] + ranked[: end - len(ranked)]

        bucket = int(now.timestamp()) // self.settings.decision_interval_seconds
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

    @staticmethod
    def _opportunity_payload(item: IntradayOpportunity) -> dict[str, float | str]:
        return {
            "symbol": item.symbol,
            "score": round(item.score, 5),
            "move_pct": round(item.move_pct, 5),
            "gap_pct": round(item.gap_pct, 5),
            "breakout_pct": round(item.breakout_pct, 5),
            "volume_pace": round(item.volume_pace, 3),
            "intraday_position": round(item.intraday_position, 3),
            "acceleration_pct": round(item.acceleration_pct, 5),
        }

    def _intraday_scan_due(self, now: datetime) -> bool:
        if not self.settings.intraday_scanner_enabled:
            return False
        if self.calendar.phase_at(now) != MarketPhase.OPEN:
            return False
        if self._last_intraday_scan is None:
            return True
        return (
            now - self._last_intraday_scan
        ).total_seconds() >= self.settings.intraday_scan_interval_seconds

    def _scan_intraday(self, api: ZerodhaApi, now: datetime) -> None:
        if not self.settings.dynamic_universe or not self._intraday_scan_due(now):
            return
        if not self._dynamic_ranked:
            self._dynamic_ranked = self._rank_dynamic_universe(now)
        pool = self._dynamic_ranked[: self.settings.intraday_scan_pool_limit]
        if not pool:
            return

        snapshots: dict[str, LiveMarketSnapshot] = {}
        batch_size = self.settings.intraday_scan_batch_size
        failed_batches = 0
        for start in range(0, len(pool), batch_size):
            batch = pool[start : start + batch_size]
            try:
                snapshots.update(api.market_snapshots(batch))
            except Exception:
                failed_batches += 1

        self._last_intraday_scan = now
        if not snapshots:
            self.operations.append_event(
                "market_data",
                "INTRADAY_SCAN_FAILED",
                {"pool_size": len(pool), "failed_batches": failed_batches},
                now,
            )
            return

        ranked = self._intraday_scanner.rank(snapshots, now)
        qualifying = [
            item
            for item in ranked
            if item.score >= self.settings.intraday_hot_score_min
        ]
        hot = qualifying[: self.settings.intraday_hot_candidates]
        with self._intraday_state_lock:
            previous_hot = self._intraday_hot
            self._intraday_hot = tuple(item.symbol for item in hot)
            self._intraday_snapshots = snapshots
            current_hot = self._intraday_hot

        self.operations.append_event(
            "market_data",
            "INTRADAY_OPPORTUNITY_SCAN",
            {
                "scanned": len(snapshots),
                "eligible_pool": len(pool),
                "failed_batches": failed_batches,
                "hot_symbols": list(current_hot),
                "new_hot_symbols": [
                    symbol for symbol in current_hot if symbol not in previous_hot
                ],
                "top": [self._opportunity_payload(item) for item in ranked[:12]],
                "minimum_hot_score": self.settings.intraday_hot_score_min,
            },
            now,
        )

    def intraday_radar_tick(self, now: datetime | None = None) -> None:
        """Run broad live scanning independently from slow multi-agent research."""
        current = now or datetime.now(IST)
        if current.tzinfo is None:
            raise ValueError("radar tick time must be timezone-aware")
        if not self.settings.dynamic_universe or not self._intraday_scan_due(current):
            return
        today = current.astimezone(IST).date().isoformat()
        if self._history_warmed_date != today:
            return
        api = self._api()
        if api is None:
            return
        self._scan_intraday(api, current)

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
        with self._intraday_state_lock:
            hot = self._intraday_hot
            snapshots = dict(self._intraday_snapshots)
        symbols = tuple(dict.fromkeys((*held, *hot, *selected)))

        result: dict[str, Quote] = {}
        for symbol in symbols:
            snapshot = snapshots.get(symbol)
            if snapshot is not None:
                result[symbol] = Quote(
                    symbol=symbol,
                    last_price=snapshot.last_price,
                    as_of=snapshot.as_of,
                )
        missing = [symbol for symbol in symbols if symbol not in result]
        if missing:
            result.update(api.quotes(missing))
        return result

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
        with self._intraday_state_lock:
            hot = self._intraday_hot
        promoted = [symbol for symbol in hot if symbol not in held_set]
        promoted_set = set(promoted)
        rotated = [
            symbol
            for symbol in self._active_dynamic_window(now)
            if symbol not in held_set and symbol not in promoted_set
        ]
        return held + promoted + rotated

    def _decision_due(self, symbol: str, now: datetime) -> bool:
        with self._intraday_state_lock:
            is_hot = symbol in self._intraday_hot
        if not is_hot:
            return super()._decision_due(symbol, now)
        raw = self.state_store.load().decisions.get(symbol.upper())
        if not raw:
            return True
        previous = datetime.fromisoformat(raw)
        return (
            now - previous
        ).total_seconds() >= self.settings.intraday_interrupt_cooldown_seconds
