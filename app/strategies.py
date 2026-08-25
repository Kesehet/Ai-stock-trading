from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.market_data import Candle


@dataclass(frozen=True)
class StrategySignal:
    symbol: str
    target_weight: float
    reason: str


class Strategy(Protocol):
    name: str

    def generate(self, symbol: str, history: list[Candle]) -> StrategySignal: ...


class BuyAndHoldStrategy:
    name = "buy_and_hold"

    def __init__(self, target_weight: float = 1.0) -> None:
        if not 0 <= target_weight <= 1:
            raise ValueError("target_weight must be between 0 and 1")
        self.target_weight = target_weight

    def generate(self, symbol: str, history: list[Candle]) -> StrategySignal:
        if not history:
            return StrategySignal(symbol=symbol, target_weight=0.0, reason="No market data")
        return StrategySignal(
            symbol=symbol,
            target_weight=self.target_weight,
            reason="Baseline buy-and-hold allocation",
        )


class MomentumStrategy:
    name = "momentum"

    def __init__(self, lookback: int = 20, target_weight: float = 1.0) -> None:
        if lookback < 2:
            raise ValueError("lookback must be at least 2")
        if not 0 <= target_weight <= 1:
            raise ValueError("target_weight must be between 0 and 1")
        self.lookback = lookback
        self.target_weight = target_weight

    def generate(self, symbol: str, history: list[Candle]) -> StrategySignal:
        if len(history) < self.lookback:
            return StrategySignal(symbol=symbol, target_weight=0.0, reason="Insufficient history")
        window = history[-self.lookback :]
        start = window[0].close
        end = window[-1].close
        momentum = (end / start) - 1
        if momentum <= 0:
            return StrategySignal(
                symbol=symbol,
                target_weight=0.0,
                reason=f"Non-positive {self.lookback}-bar momentum: {momentum:.4f}",
            )
        return StrategySignal(
            symbol=symbol,
            target_weight=self.target_weight,
            reason=f"Positive {self.lookback}-bar momentum: {momentum:.4f}",
        )
