from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from statistics import mean

from app.market_data import HistoricalDataStore
from app.models import Position


@dataclass(frozen=True)
class PortfolioContext:
    symbol: str
    position_weight: float
    gross_exposure: float
    cash_weight: float
    max_pair_correlation: float | None
    most_correlated_symbol: str | None

    def as_text(self) -> str:
        corr = "NA" if self.max_pair_correlation is None else f"{self.max_pair_correlation:.4f}"
        peer = self.most_correlated_symbol or "NA"
        return "\n".join(
            [
                f"position_weight={self.position_weight:.4f}",
                f"gross_exposure={self.gross_exposure:.4f}",
                f"cash_weight={self.cash_weight:.4f}",
                f"max_pair_correlation={corr}",
                f"most_correlated_symbol={peer}",
            ]
        )


def _correlation(left: list[float], right: list[float]) -> float | None:
    count = min(len(left), len(right))
    if count < 5:
        return None
    a = left[-count:]
    b = right[-count:]
    avg_a = mean(a)
    avg_b = mean(b)
    numerator = sum((x - avg_a) * (y - avg_b) for x, y in zip(a, b, strict=True))
    denom_a = sqrt(sum((x - avg_a) ** 2 for x in a))
    denom_b = sqrt(sum((y - avg_b) ** 2 for y in b))
    if denom_a == 0 or denom_b == 0:
        return None
    return numerator / (denom_a * denom_b)


def _returns(closes: list[float]) -> list[float]:
    return [
        (closes[index] / closes[index - 1]) - 1
        for index in range(1, len(closes))
        if closes[index - 1] > 0
    ]


def build_portfolio_context(
    *,
    symbol: str,
    positions: list[Position],
    cash: float,
    market_data: HistoricalDataStore,
    as_of,
    lookback: int = 60,
) -> PortfolioContext:
    values: dict[str, float] = {}
    for position in positions:
        latest = market_data.latest_as_of(position.symbol, as_of)
        if latest is not None:
            values[position.symbol.upper()] = position.quantity * latest.close
    invested = sum(values.values())
    equity = cash + invested
    gross = invested / equity if equity > 0 else 0.0
    target_value = values.get(symbol.upper(), 0.0)
    target_weight = target_value / equity if equity > 0 else 0.0
    cash_weight = cash / equity if equity > 0 else 0.0

    target_candles = market_data.as_of(symbol, as_of, limit=lookback)
    target_returns = _returns([item.close for item in target_candles])
    best_corr: float | None = None
    best_symbol: str | None = None
    for peer in values:
        if peer == symbol.upper():
            continue
        peer_candles = market_data.as_of(peer, as_of, limit=lookback)
        corr = _correlation(target_returns, _returns([item.close for item in peer_candles]))
        if corr is not None and (best_corr is None or abs(corr) > abs(best_corr)):
            best_corr = corr
            best_symbol = peer

    return PortfolioContext(
        symbol=symbol.upper(),
        position_weight=target_weight,
        gross_exposure=gross,
        cash_weight=cash_weight,
        max_pair_correlation=best_corr,
        most_correlated_symbol=best_symbol,
    )
