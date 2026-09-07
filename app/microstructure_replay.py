from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from math import floor

from app.microstructure import BookTick, MicroFeatures, MicrostructureConfig, MicrostructureEngine
from app.microstructure_models import ForecastModel, default_models, fit_chronological_logistic


@dataclass(frozen=True)
class ReplayConfig:
    starting_nav: float = 500.0
    max_position_pct: float = 0.50
    horizons: tuple[int, ...] = (1, 2, 3, 5, 10)
    latency_events: int = 1
    target_ticks: int = 4
    stop_ticks: int = 3
    min_probability: float = 0.68
    min_expected_net_rupees: float = 0.10
    tick_size: float = 0.05
    slippage_bps_each_way: float = 5.0
    training_fraction: float = 0.60
    min_training_samples: int = 100


@dataclass(frozen=True)
class EventLabel:
    symbol: str
    event_index: int
    horizon_events: int
    direction: int
    move_ticks: float
    mfe_ticks: float
    mae_ticks: float


@dataclass(frozen=True)
class ShadowTrade:
    model: str
    horizon_events: int
    symbol: str
    signal_timestamp: datetime
    entry_timestamp: datetime
    exit_timestamp: datetime
    probability_up: float
    quantity: int
    entry_price: float
    exit_price: float
    exit_reason: str
    gross_pnl: float
    costs: float
    net_pnl: float
    mfe_ticks: float
    mae_ticks: float
    direction_correct: bool


@dataclass(frozen=True)
class StrategyScore:
    model: str
    horizon_events: int
    trades: int
    wins: int
    hit_rate: float
    gross_pnl: float
    costs: float
    net_pnl: float
    net_expectancy: float
    profit_factor: float
    max_drawdown: float
    starting_nav: float
    ending_nav: float


@dataclass(frozen=True)
class ReplayReport:
    scores: tuple[StrategyScore, ...]
    trades: tuple[ShadowTrade, ...]
    labels: tuple[EventLabel, ...]
    fitted_models: int


@dataclass(frozen=True)
class _Candidate:
    model: str
    horizon_events: int
    symbol: str
    signal_timestamp: datetime
    entry_timestamp: datetime
    exit_timestamp: datetime
    probability_up: float
    entry_price: float
    exit_price: float
    exit_reason: str
    mfe_ticks: float
    mae_ticks: float
    direction_correct: bool


class MicrostructureReplay:
    """Chronological, no-lookahead shadow replay for recorded depth events.

    Signals use only information available at the signal event. Entry is delayed by
    configured event latency and pays the observed ask. Long exits receive the
    observed bid at the first target/stop touch or at horizon expiry.
    """

    def __init__(self, config: ReplayConfig | None = None) -> None:
        self.config = config or ReplayConfig()
        if self.config.starting_nav <= 0:
            raise ValueError("starting_nav must be positive")
        if not 0 < self.config.training_fraction < 1:
            raise ValueError("training_fraction must be between zero and one")
        if self.config.latency_events < 1:
            raise ValueError("latency_events must be at least one")
        self._feature_engine = MicrostructureEngine(
            MicrostructureConfig(
                bankroll=self.config.starting_nav,
                max_position_pct=self.config.max_position_pct,
                tick_size=self.config.tick_size,
                slippage_bps_each_way=self.config.slippage_bps_each_way,
            )
        )

    def run(self, ticks: Iterable[BookTick]) -> ReplayReport:
        by_symbol = _group_ticks(ticks)
        labels: list[EventLabel] = []
        features_by_symbol: dict[str, list[MicroFeatures | None]] = {}
        test_start_by_symbol: dict[str, int] = {}

        for symbol, series in by_symbol.items():
            features_by_symbol[symbol] = self._features(series)
            labels.extend(make_event_labels(series, self.config.horizons, self.config.tick_size))
            test_start_by_symbol[symbol] = max(
                1,
                int(len(series) * self.config.training_fraction),
            )

        models_by_horizon: dict[int, list[ForecastModel]] = {}
        fitted_models = 0
        for horizon in self.config.horizons:
            models = list(default_models())
            training = self._training_samples(
                by_symbol,
                features_by_symbol,
                test_start_by_symbol,
                horizon,
            )
            if len(training) >= self.config.min_training_samples:
                fitted = fit_chronological_logistic(training)
                models.append(fitted)
                fitted_models += 1
            models_by_horizon[horizon] = models

        all_trades: list[ShadowTrade] = []
        scores: list[StrategyScore] = []
        for horizon, models in models_by_horizon.items():
            for model in models:
                candidates = self._candidates(
                    model,
                    horizon,
                    by_symbol,
                    features_by_symbol,
                    test_start_by_symbol,
                )
                trades, score = self._simulate(model.name, horizon, candidates)
                all_trades.extend(trades)
                scores.append(score)

        scores.sort(key=lambda item: (item.net_pnl, item.trades), reverse=True)
        all_trades.sort(key=lambda item: item.signal_timestamp)
        return ReplayReport(
            scores=tuple(scores),
            trades=tuple(all_trades),
            labels=tuple(labels),
            fitted_models=fitted_models,
        )

    def _features(self, series: Sequence[BookTick]) -> list[MicroFeatures | None]:
        result: list[MicroFeatures | None] = []
        previous: BookTick | None = None
        for tick in series:
            if not tick.bids or not tick.asks:
                result.append(None)
            else:
                result.append(self._feature_engine.features(tick, previous))
            previous = tick
        return result

    def _training_samples(
        self,
        by_symbol: dict[str, list[BookTick]],
        features_by_symbol: dict[str, list[MicroFeatures | None]],
        test_start_by_symbol: dict[str, int],
        horizon: int,
    ) -> list[tuple[MicroFeatures, int]]:
        samples: list[tuple[MicroFeatures, int]] = []
        for symbol, series in by_symbol.items():
            cutoff = test_start_by_symbol[symbol]
            features = features_by_symbol[symbol]
            for index in range(1, min(cutoff, len(series) - horizon)):
                feature = features[index]
                if feature is None:
                    continue
                current = _mid(series[index])
                future = _mid(series[index + horizon])
                if current is None or future is None or future == current:
                    continue
                samples.append((feature, 1 if future > current else 0))
        return samples

    def _candidates(
        self,
        model: ForecastModel,
        horizon: int,
        by_symbol: dict[str, list[BookTick]],
        features_by_symbol: dict[str, list[MicroFeatures | None]],
        test_start_by_symbol: dict[str, int],
    ) -> list[_Candidate]:
        candidates: list[_Candidate] = []
        for symbol, series in by_symbol.items():
            features = features_by_symbol[symbol]
            start = test_start_by_symbol[symbol]
            final_signal = len(series) - self.config.latency_events - horizon
            for index in range(start, max(start, final_signal)):
                feature = features[index]
                if feature is None:
                    continue
                forecast = model.forecast(feature, horizon)
                if forecast.probability_up < self.config.min_probability:
                    continue
                candidate = self._resolve_candidate(
                    series,
                    index,
                    horizon,
                    model.name,
                    forecast.probability_up,
                )
                if candidate is not None:
                    candidates.append(candidate)
        candidates.sort(key=lambda item: item.signal_timestamp)
        return candidates

    def _resolve_candidate(
        self,
        series: Sequence[BookTick],
        signal_index: int,
        horizon: int,
        model_name: str,
        probability_up: float,
    ) -> _Candidate | None:
        entry_index = signal_index + self.config.latency_events
        if entry_index >= len(series) or not series[entry_index].asks:
            return None
        entry_tick = series[entry_index]
        entry = entry_tick.asks[0].price
        if entry <= 0:
            return None

        target = entry + self.config.target_ticks * self.config.tick_size
        stop = entry - self.config.stop_ticks * self.config.tick_size
        end_index = min(entry_index + horizon, len(series) - 1)
        future = [tick for tick in series[entry_index + 1 : end_index + 1] if tick.bids]
        if not future:
            return None

        observed_bids = [tick.bids[0].price for tick in future]
        mfe_ticks = (max(observed_bids) - entry) / self.config.tick_size
        mae_ticks = (min(observed_bids) - entry) / self.config.tick_size
        exit_tick = future[-1]
        exit_price = exit_tick.bids[0].price
        exit_reason = "expiry"
        for tick in future:
            bid = tick.bids[0].price
            if bid <= stop:
                exit_tick = tick
                exit_price = bid
                exit_reason = "stop"
                break
            if bid >= target:
                exit_tick = tick
                exit_price = bid
                exit_reason = "target"
                break

        return _Candidate(
            model=model_name,
            horizon_events=horizon,
            symbol=entry_tick.symbol,
            signal_timestamp=series[signal_index].timestamp,
            entry_timestamp=entry_tick.timestamp,
            exit_timestamp=exit_tick.timestamp,
            probability_up=probability_up,
            entry_price=entry,
            exit_price=exit_price,
            exit_reason=exit_reason,
            mfe_ticks=mfe_ticks,
            mae_ticks=mae_ticks,
            direction_correct=exit_price > entry,
        )

    def _simulate(
        self,
        model_name: str,
        horizon: int,
        candidates: Sequence[_Candidate],
    ) -> tuple[list[ShadowTrade], StrategyScore]:
        nav = self.config.starting_nav
        peak = nav
        max_drawdown = 0.0
        busy_until: datetime | None = None
        trades: list[ShadowTrade] = []

        for candidate in candidates:
            if busy_until is not None and candidate.signal_timestamp <= busy_until:
                continue
            position_cap = min(nav, nav * self.config.max_position_pct)
            quantity = floor(position_cap / candidate.entry_price)
            if quantity < 1:
                continue

            target_price = candidate.entry_price + self.config.target_ticks * self.config.tick_size
            gross_win = (target_price - candidate.entry_price) * quantity
            gross_loss = self.config.stop_ticks * self.config.tick_size * quantity
            expected_cost = self._feature_engine.estimate_intraday_round_trip_cost(
                candidate.entry_price,
                target_price,
                quantity,
            )
            expected_net = (
                candidate.probability_up * gross_win
                - (1.0 - candidate.probability_up) * gross_loss
                - expected_cost
            )
            if expected_net < self.config.min_expected_net_rupees:
                continue

            gross = (candidate.exit_price - candidate.entry_price) * quantity
            costs = self._feature_engine.estimate_intraday_round_trip_cost(
                candidate.entry_price,
                candidate.exit_price,
                quantity,
            )
            net = gross - costs
            nav += net
            peak = max(peak, nav)
            max_drawdown = max(max_drawdown, peak - nav)
            busy_until = candidate.exit_timestamp
            trades.append(
                ShadowTrade(
                    model=model_name,
                    horizon_events=horizon,
                    symbol=candidate.symbol,
                    signal_timestamp=candidate.signal_timestamp,
                    entry_timestamp=candidate.entry_timestamp,
                    exit_timestamp=candidate.exit_timestamp,
                    probability_up=candidate.probability_up,
                    quantity=quantity,
                    entry_price=candidate.entry_price,
                    exit_price=candidate.exit_price,
                    exit_reason=candidate.exit_reason,
                    gross_pnl=gross,
                    costs=costs,
                    net_pnl=net,
                    mfe_ticks=candidate.mfe_ticks,
                    mae_ticks=candidate.mae_ticks,
                    direction_correct=candidate.direction_correct,
                )
            )

        gross_pnl = sum(trade.gross_pnl for trade in trades)
        costs = sum(trade.costs for trade in trades)
        net_pnl = sum(trade.net_pnl for trade in trades)
        wins = sum(1 for trade in trades if trade.net_pnl > 0)
        hits = sum(1 for trade in trades if trade.direction_correct)
        gains = sum(trade.net_pnl for trade in trades if trade.net_pnl > 0)
        losses = -sum(trade.net_pnl for trade in trades if trade.net_pnl < 0)
        profit_factor = gains / losses if losses > 0 else (gains if gains > 0 else 0.0)
        count = len(trades)
        score = StrategyScore(
            model=model_name,
            horizon_events=horizon,
            trades=count,
            wins=wins,
            hit_rate=hits / count if count else 0.0,
            gross_pnl=gross_pnl,
            costs=costs,
            net_pnl=net_pnl,
            net_expectancy=net_pnl / count if count else 0.0,
            profit_factor=profit_factor,
            max_drawdown=max_drawdown,
            starting_nav=self.config.starting_nav,
            ending_nav=self.config.starting_nav + net_pnl,
        )
        return trades, score


def make_event_labels(
    series: Sequence[BookTick],
    horizons: Sequence[int] = (1, 2, 3, 5, 10),
    tick_size: float = 0.05,
) -> list[EventLabel]:
    labels: list[EventLabel] = []
    if tick_size <= 0:
        raise ValueError("tick_size must be positive")
    for index, tick in enumerate(series):
        current = _mid(tick)
        if current is None:
            continue
        for horizon in horizons:
            if horizon < 1 or index + horizon >= len(series):
                continue
            window = series[index + 1 : index + horizon + 1]
            mids = [mid for item in window if (mid := _mid(item)) is not None]
            if not mids:
                continue
            future = mids[-1]
            direction = 1 if future > current else (-1 if future < current else 0)
            labels.append(
                EventLabel(
                    symbol=tick.symbol,
                    event_index=index,
                    horizon_events=horizon,
                    direction=direction,
                    move_ticks=(future - current) / tick_size,
                    mfe_ticks=(max(mids) - current) / tick_size,
                    mae_ticks=(min(mids) - current) / tick_size,
                )
            )
    return labels


def _group_ticks(ticks: Iterable[BookTick]) -> dict[str, list[BookTick]]:
    grouped: dict[str, list[BookTick]] = defaultdict(list)
    for tick in ticks:
        if tick.bids and tick.asks:
            grouped[tick.symbol].append(tick)
    for series in grouped.values():
        series.sort(key=lambda item: item.timestamp)
    return dict(grouped)


def _mid(tick: BookTick) -> float | None:
    if not tick.bids or not tick.asks:
        return None
    return (tick.bids[0].price + tick.asks[0].price) / 2.0
