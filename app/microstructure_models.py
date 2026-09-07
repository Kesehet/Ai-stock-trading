from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import exp
from typing import Protocol

from app.microstructure import HorizonForecast, MicroFeatures


class ForecastModel(Protocol):
    @property
    def name(self) -> str: ...

    def forecast(self, features: MicroFeatures, horizon_events: int) -> HorizonForecast: ...


@dataclass(frozen=True)
class QueueImbalanceModel:
    name: str = "queue_imbalance"

    def forecast(self, f: MicroFeatures, horizon_events: int) -> HorizonForecast:
        score = 0.60 * f.level1_imbalance + 0.40 * f.weighted_imbalance
        return _forecast(score, horizon_events)


@dataclass(frozen=True)
class MicropriceMomentumModel:
    name: str = "microprice_momentum"

    def forecast(self, f: MicroFeatures, horizon_events: int) -> HorizonForecast:
        microprice = _clip(f.microprice_ticks, -1.0, 1.0)
        score = 0.65 * microprice + 0.35 * f.trade_momentum
        return _forecast(score, horizon_events)


@dataclass(frozen=True)
class FlowMomentumModel:
    name: str = "flow_momentum"

    def forecast(self, f: MicroFeatures, horizon_events: int) -> HorizonForecast:
        score = 0.65 * f.order_flow_imbalance + 0.35 * f.trade_momentum
        return _forecast(score, horizon_events)


@dataclass(frozen=True)
class EnsembleModel:
    name: str = "book_ensemble"

    def forecast(self, f: MicroFeatures, horizon_events: int) -> HorizonForecast:
        score = (
            0.30 * f.level1_imbalance
            + 0.25 * f.weighted_imbalance
            + 0.20 * _clip(f.microprice_ticks, -1.0, 1.0)
            + 0.15 * f.order_flow_imbalance
            + 0.10 * f.trade_momentum
        )
        return _forecast(score, horizon_events)


@dataclass(frozen=True)
class ChronologicalLogisticModel:
    """Small fitted baseline trained only on earlier chronological observations."""

    coefficients: tuple[float, float, float, float, float]
    intercept: float
    name: str = "chronological_logit"

    def forecast(self, f: MicroFeatures, horizon_events: int) -> HorizonForecast:
        x = feature_vector(f)
        z = self.intercept + sum(
            weight * value for weight, value in zip(self.coefficients, x, strict=True)
        )
        probability_up = _sigmoid(z)
        probability_up = _shrink_for_horizon(probability_up, horizon_events)
        return HorizonForecast(
            horizon_events=horizon_events,
            probability_up=probability_up,
            probability_down=1.0 - probability_up,
            score=2.0 * (probability_up - 0.5),
        )


def default_models() -> tuple[ForecastModel, ...]:
    models: tuple[ForecastModel, ...] = (
        QueueImbalanceModel(),
        MicropriceMomentumModel(),
        FlowMomentumModel(),
        EnsembleModel(),
    )
    return models


def fit_chronological_logistic(
    samples: Sequence[tuple[MicroFeatures, int]],
    *,
    epochs: int = 100,
    learning_rate: float = 0.08,
    l2: float = 0.01,
) -> ChronologicalLogisticModel:
    if len(samples) < 20:
        raise ValueError("at least 20 chronological samples are required")
    if epochs < 1:
        raise ValueError("epochs must be positive")
    if learning_rate <= 0:
        raise ValueError("learning_rate must be positive")

    weights = [0.0] * 5
    intercept = 0.0
    scale = float(len(samples))
    for _ in range(epochs):
        grad = [0.0] * 5
        grad_intercept = 0.0
        for features, label in samples:
            if label not in (0, 1):
                raise ValueError("labels must be 0 or 1")
            x = feature_vector(features)
            z = intercept + sum(
                weight * value for weight, value in zip(weights, x, strict=True)
            )
            error = _sigmoid(z) - float(label)
            grad_intercept += error
            for index, value in enumerate(x):
                grad[index] += error * value
        intercept -= learning_rate * grad_intercept / scale
        for index in range(5):
            regularized = grad[index] / scale + l2 * weights[index]
            weights[index] -= learning_rate * regularized

    return ChronologicalLogisticModel(
        coefficients=(weights[0], weights[1], weights[2], weights[3], weights[4]),
        intercept=intercept,
    )


def feature_vector(f: MicroFeatures) -> tuple[float, float, float, float, float]:
    return (
        _clip(f.level1_imbalance, -1.0, 1.0),
        _clip(f.weighted_imbalance, -1.0, 1.0),
        _clip(f.microprice_ticks, -1.0, 1.0),
        _clip(f.order_flow_imbalance, -1.0, 1.0),
        _clip(f.trade_momentum, -1.0, 1.0),
    )


def _forecast(score: float, horizon_events: int) -> HorizonForecast:
    probability_up = _clip(0.5 + 0.45 * _clip(score, -1.0, 1.0), 0.02, 0.98)
    probability_up = _shrink_for_horizon(probability_up, horizon_events)
    return HorizonForecast(
        horizon_events=horizon_events,
        probability_up=probability_up,
        probability_down=1.0 - probability_up,
        score=score,
    )


def _shrink_for_horizon(probability: float, horizon_events: int) -> float:
    scale = {1: 1.0, 2: 0.94, 3: 0.88, 5: 0.76, 10: 0.60}.get(horizon_events, 0.55)
    return _clip(0.5 + (probability - 0.5) * scale, 0.02, 0.98)


def _sigmoid(value: float) -> float:
    clipped = _clip(value, -20.0, 20.0)
    return 1.0 / (1.0 + exp(-clipped))


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
