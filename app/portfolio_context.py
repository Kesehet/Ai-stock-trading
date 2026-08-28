from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
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
    held_quantity: int = 0
    average_cost: float | None = None
    mark_price: float | None = None
    unrealized_pnl: float | None = None
    unrealized_pnl_pct: float | None = None

    def as_text(self) -> str:
        corr = "NA" if self.max_pair_correlation is None else f"{self.max_pair_correlation:.4f}"
        peer = self.most_correlated_symbol or "NA"
        average_cost = "NA" if self.average_cost is None else f"{self.average_cost:.4f}"
        mark_price = "NA" if self.mark_price is None else f"{self.mark_price:.4f}"
        unrealized = "NA" if self.unrealized_pnl is None else f"{self.unrealized_pnl:.2f}"
        unrealized_pct = (
            "NA" if self.unrealized_pnl_pct is None else f"{self.unrealized_pnl_pct:.4f}"
        )
        return "\n".join(
            [
                f"position_weight={self.position_weight:.4f}",
                f"gross_exposure={self.gross_exposure:.4f}",
                f"cash_weight={self.cash_weight:.4f}",
                f"max_pair_correlation={corr}",
                f"most_correlated_symbol={peer}",
                f"held_quantity={self.held_quantity}",
                f"average_cost={average_cost}",
                f"mark_price={mark_price}",
                f"unrealized_pnl={unrealized}",
                f"unrealized_pnl_pct={unrealized_pct}",
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
    as_of: datetime,
    live_prices: Mapping[str, float] | None = None,
    lookback: int = 60,
) -> PortfolioContext:
    normalized_symbol = symbol.upper()
    normalized_live_prices = {
        key.upper(): float(value)
        for key, value in (live_prices or {}).items()
        if float(value) > 0
    }
    values: dict[str, float] = {}
    for position in positions:
        position_symbol = position.symbol.upper()
        live_price = normalized_live_prices.get(position_symbol)
        if live_price is not None:
            values[position_symbol] = position.quantity * live_price
            continue
        latest = market_data.latest_as_of(position.symbol, as_of)
        if latest is not None:
            values[position_symbol] = position.quantity * latest.close

    invested = sum(values.values())
    equity = cash + invested
    gross = invested / equity if equity > 0 else 0.0
    target_value = values.get(normalized_symbol, 0.0)
    target_weight = target_value / equity if equity > 0 else 0.0
    cash_weight = cash / equity if equity > 0 else 0.0

    matching_positions = [
        position for position in positions if position.symbol.upper() == normalized_symbol
    ]
    held_quantity = sum(position.quantity for position in matching_positions)
    cost_basis = sum(
        position.quantity * position.average_price for position in matching_positions
    )
    average_cost = cost_basis / held_quantity if held_quantity > 0 else None
    mark_price = normalized_live_prices.get(normalized_symbol)
    if mark_price is None:
        latest = market_data.latest_as_of(normalized_symbol, as_of)
        mark_price = latest.close if latest is not None else None
    unrealized_pnl: float | None = None
    unrealized_pnl_pct: float | None = None
    if held_quantity > 0 and average_cost is not None and mark_price is not None:
        unrealized_pnl = held_quantity * (mark_price - average_cost)
        unrealized_pnl_pct = (mark_price / average_cost) - 1 if average_cost > 0 else None

    target_candles = market_data.as_of(symbol, as_of, limit=lookback)
    target_returns = _returns([item.close for item in target_candles])
    best_corr: float | None = None
    best_symbol: str | None = None
    for peer in values:
        if peer == normalized_symbol:
            continue
        peer_candles = market_data.as_of(peer, as_of, limit=lookback)
        corr = _correlation(target_returns, _returns([item.close for item in peer_candles]))
        if corr is not None and (best_corr is None or abs(corr) > abs(best_corr)):
            best_corr = corr
            best_symbol = peer

    return PortfolioContext(
        symbol=normalized_symbol,
        position_weight=target_weight,
        gross_exposure=gross,
        cash_weight=cash_weight,
        max_pair_correlation=best_corr,
        most_correlated_symbol=best_symbol,
        held_quantity=held_quantity,
        average_cost=average_cost,
        mark_price=mark_price,
        unrealized_pnl=unrealized_pnl,
        unrealized_pnl_pct=unrealized_pnl_pct,
    )
