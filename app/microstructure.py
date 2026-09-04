from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime
from math import floor


@dataclass(frozen=True)
class BookLevel:
    price: float
    quantity: int
    orders: int = 0


@dataclass(frozen=True)
class BookTick:
    symbol: str
    timestamp: datetime
    last_price: float
    last_quantity: int
    volume: int
    bids: tuple[BookLevel, ...]
    asks: tuple[BookLevel, ...]


@dataclass(frozen=True)
class MicroFeatures:
    mid: float
    spread: float
    microprice: float
    microprice_ticks: float
    level1_imbalance: float
    weighted_imbalance: float
    order_flow_imbalance: float
    trade_momentum: float


@dataclass(frozen=True)
class HorizonForecast:
    horizon_events: int
    probability_up: float
    probability_down: float
    score: float


@dataclass(frozen=True)
class ShadowOpportunity:
    symbol: str
    timestamp: datetime
    quantity: int
    entry_limit: float
    target: float
    stop: float
    expected_gross_rupees: float
    estimated_round_trip_cost: float
    expected_net_rupees: float
    forecast: HorizonForecast
    features: MicroFeatures


@dataclass(frozen=True)
class MicrostructureConfig:
    tick_size: float = 0.05
    bankroll: float = 500.0
    max_position_pct: float = 0.50
    max_horizon_events: int = 5
    target_ticks: int = 4
    stop_ticks: int = 3
    min_probability: float = 0.68
    min_expected_net_rupees: float = 0.35
    slippage_bps_each_way: float = 5.0


class MicrostructureEngine:
    """Fast, deterministic research layer for event-level shadow trading.

    It never places an order. It converts top-five book snapshots into features,
    forecasts 1/3/5-event direction with transparent models and applies ₹500
    whole-share economics before emitting a shadow opportunity.
    """

    def __init__(self, config: MicrostructureConfig | None = None) -> None:
        self.config = config or MicrostructureConfig()
        self._history: dict[str, deque[BookTick]] = {}

    def on_tick(self, tick: BookTick) -> list[ShadowOpportunity]:
        if not tick.bids or not tick.asks:
            return []
        history = self._history.setdefault(tick.symbol, deque(maxlen=64))
        previous = history[-1] if history else None
        history.append(tick)
        features = self.features(tick, previous)
        opportunities: list[ShadowOpportunity] = []
        for horizon in (1, 3, 5):
            forecast = self.forecast(features, horizon)
            opportunity = self._economically_executable(tick, features, forecast)
            if opportunity is not None:
                opportunities.append(opportunity)
        return opportunities

    def features(self, tick: BookTick, previous: BookTick | None) -> MicroFeatures:
        bid = tick.bids[0].price
        ask = tick.asks[0].price
        spread = max(ask - bid, self.config.tick_size)
        mid = (bid + ask) / 2.0
        bid_q = max(tick.bids[0].quantity, 0)
        ask_q = max(tick.asks[0].quantity, 0)
        denom = bid_q + ask_q
        imbalance = (bid_q - ask_q) / denom if denom else 0.0
        microprice = (ask * bid_q + bid * ask_q) / denom if denom else mid
        weights = (1.0, 0.7, 0.5, 0.35, 0.25)
        weighted_bid = sum(
            level.quantity * weights[i] for i, level in enumerate(tick.bids[:5])
        )
        weighted_ask = sum(
            level.quantity * weights[i] for i, level in enumerate(tick.asks[:5])
        )
        weighted_total = weighted_bid + weighted_ask
        weighted_imbalance = (
            (weighted_bid - weighted_ask) / weighted_total if weighted_total else 0.0
        )
        ofi = self._order_flow_imbalance(tick, previous)
        momentum = self._trade_momentum(tick, previous)
        return MicroFeatures(
            mid=mid,
            spread=spread,
            microprice=microprice,
            microprice_ticks=(microprice - mid) / self.config.tick_size,
            level1_imbalance=imbalance,
            weighted_imbalance=weighted_imbalance,
            order_flow_imbalance=ofi,
            trade_momentum=momentum,
        )

    def forecast(self, f: MicroFeatures, horizon_events: int) -> HorizonForecast:
        horizon_scale = {1: 1.0, 3: 0.88, 5: 0.76}.get(horizon_events, 0.70)
        score = horizon_scale * (
            0.30 * f.level1_imbalance
            + 0.25 * f.weighted_imbalance
            + 0.20 * self._clip(f.microprice_ticks, -1.0, 1.0)
            + 0.15 * f.order_flow_imbalance
            + 0.10 * f.trade_momentum
        )
        # Deliberately conservative calibration until NSE event data can fit it.
        probability_up = self._clip(0.5 + 0.45 * score, 0.02, 0.98)
        return HorizonForecast(
            horizon_events=horizon_events,
            probability_up=probability_up,
            probability_down=1.0 - probability_up,
            score=score,
        )

    def _economically_executable(
        self, tick: BookTick, f: MicroFeatures, forecast: HorizonForecast
    ) -> ShadowOpportunity | None:
        if forecast.probability_up < self.config.min_probability:
            return None
        entry = tick.asks[0].price
        position_cap = self.config.bankroll * self.config.max_position_pct
        quantity = floor(position_cap / entry)
        if quantity < 1:
            return None
        target = entry + self.config.target_ticks * self.config.tick_size
        stop = entry - self.config.stop_ticks * self.config.tick_size
        gross_win = (target - entry) * quantity
        gross_loss = (entry - stop) * quantity
        costs = self.estimate_intraday_round_trip_cost(entry, target, quantity)
        expected_net = (
            forecast.probability_up * gross_win
            - forecast.probability_down * gross_loss
            - costs
        )
        if expected_net < self.config.min_expected_net_rupees:
            return None
        return ShadowOpportunity(
            symbol=tick.symbol,
            timestamp=tick.timestamp,
            quantity=quantity,
            entry_limit=entry,
            target=target,
            stop=stop,
            expected_gross_rupees=gross_win,
            estimated_round_trip_cost=costs,
            expected_net_rupees=expected_net,
            forecast=forecast,
            features=f,
        )

    def estimate_intraday_round_trip_cost(
        self, buy_price: float, sell_price: float, quantity: int
    ) -> float:
        buy_value = buy_price * quantity
        sell_value = sell_price * quantity
        turnover = buy_value + sell_value
        brokerage = min(20.0, buy_value * 0.0003) + min(20.0, sell_value * 0.0003)
        # Conservative NSE-equity approximations; centralize against app.costs next.
        stt = sell_value * 0.00025
        exchange = turnover * 0.0000297
        sebi = turnover * 0.000001
        stamp = buy_value * 0.00003
        gst = (brokerage + exchange + sebi) * 0.18
        slippage = turnover * (self.config.slippage_bps_each_way / 10_000.0)
        return brokerage + stt + exchange + sebi + stamp + gst + slippage

    @staticmethod
    def _order_flow_imbalance(tick: BookTick, previous: BookTick | None) -> float:
        if previous is None or not previous.bids or not previous.asks:
            return 0.0
        bid_delta = tick.bids[0].quantity - previous.bids[0].quantity
        ask_delta = tick.asks[0].quantity - previous.asks[0].quantity
        scale = max(
            tick.bids[0].quantity + tick.asks[0].quantity,
            previous.bids[0].quantity + previous.asks[0].quantity,
            1,
        )
        return MicrostructureEngine._clip((bid_delta - ask_delta) / scale, -1.0, 1.0)

    @staticmethod
    def _trade_momentum(tick: BookTick, previous: BookTick | None) -> float:
        if previous is None:
            return 0.0
        price_change = tick.last_price - previous.last_price
        if price_change == 0:
            return 0.0
        direction = 1.0 if price_change > 0 else -1.0
        volume_delta = max(tick.volume - previous.volume, tick.last_quantity, 0)
        liquidity = max(tick.bids[0].quantity + tick.asks[0].quantity, 1)
        return MicrostructureEngine._clip(direction * volume_delta / liquidity, -1.0, 1.0)

    @staticmethod
    def _clip(value: float, low: float, high: float) -> float:
        return max(low, min(high, value))
