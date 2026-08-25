from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from statistics import mean, pstdev

from app.market_data import Candle


@dataclass(frozen=True)
class TechnicalFeatures:
    close: float
    sma_20: float | None
    sma_50: float | None
    ema_12: float | None
    ema_26: float | None
    rsi_14: float | None
    return_5d: float | None
    return_20d: float | None
    volatility_20d: float | None
    volume_ratio_20d: float | None
    distance_from_20d_high_pct: float | None

    def as_text(self) -> str:
        values = {
            "close": self.close,
            "sma_20": self.sma_20,
            "sma_50": self.sma_50,
            "ema_12": self.ema_12,
            "ema_26": self.ema_26,
            "rsi_14": self.rsi_14,
            "return_5d": self.return_5d,
            "return_20d": self.return_20d,
            "volatility_20d": self.volatility_20d,
            "volume_ratio_20d": self.volume_ratio_20d,
            "distance_from_20d_high_pct": self.distance_from_20d_high_pct,
        }
        return "\n".join(
            f"{key}={value:.4f}" if isinstance(value, float) else f"{key}=NA"
            for key, value in values.items()
        )


def _sma(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    return mean(values[-period:])


def _ema(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    multiplier = 2 / (period + 1)
    result = mean(values[:period])
    for value in values[period:]:
        result = (value * multiplier) + (result * (1 - multiplier))
    return result


def _rsi(values: list[float], period: int = 14) -> float | None:
    if len(values) <= period:
        return None
    changes = [values[index] - values[index - 1] for index in range(1, len(values))]
    recent = changes[-period:]
    gains = [max(change, 0.0) for change in recent]
    losses = [max(-change, 0.0) for change in recent]
    avg_gain = mean(gains)
    avg_loss = mean(losses)
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calculate_technical_features(candles: list[Candle]) -> TechnicalFeatures:
    if not candles:
        raise ValueError("at least one candle is required")
    ordered = sorted(candles, key=lambda candle: candle.timestamp)
    closes = [candle.close for candle in ordered]
    volumes = [candle.volume for candle in ordered]

    def period_return(period: int) -> float | None:
        if len(closes) <= period:
            return None
        return (closes[-1] / closes[-1 - period]) - 1

    daily_returns = [
        (closes[index] / closes[index - 1]) - 1 for index in range(1, len(closes))
    ]
    volatility = None
    if len(daily_returns) >= 20:
        volatility = pstdev(daily_returns[-20:]) * sqrt(252)

    volume_ratio = None
    if len(volumes) >= 20:
        avg_volume = mean(volumes[-20:])
        if avg_volume > 0:
            volume_ratio = volumes[-1] / avg_volume

    distance = None
    if len(closes) >= 20:
        high_20 = max(closes[-20:])
        distance = (closes[-1] / high_20) - 1

    return TechnicalFeatures(
        close=closes[-1],
        sma_20=_sma(closes, 20),
        sma_50=_sma(closes, 50),
        ema_12=_ema(closes, 12),
        ema_26=_ema(closes, 26),
        rsi_14=_rsi(closes, 14),
        return_5d=period_return(5),
        return_20d=period_return(20),
        volatility_20d=volatility,
        volume_ratio_20d=volume_ratio,
        distance_from_20d_high_pct=distance,
    )
