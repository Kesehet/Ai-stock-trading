from __future__ import annotations

from dataclasses import dataclass
from math import floor, sqrt
from statistics import mean, pstdev

from app.backtest import CostModel
from app.market_data import Candle
from app.strategies import Strategy


@dataclass(frozen=True)
class SimulatedTrade:
    signal_at: object
    executed_at: object
    symbol: str
    side: str
    quantity: int
    price: float
    costs: float


@dataclass(frozen=True)
class SimulationMetrics:
    starting_cash: float
    ending_equity: float
    total_return: float
    max_drawdown: float
    sharpe: float
    sortino: float
    turnover: float
    trades: tuple[SimulatedTrade, ...]
    equity_curve: tuple[float, ...]


class NextBarBacktester:
    """Target-weight backtester that generates at bar close and fills next bar open."""

    def __init__(self, starting_cash: float, costs: CostModel | None = None) -> None:
        if starting_cash <= 0:
            raise ValueError("starting_cash must be positive")
        self.starting_cash = starting_cash
        self.costs = costs or CostModel()

    def run(self, symbol: str, candles: list[Candle], strategy: Strategy) -> SimulationMetrics:
        ordered = sorted(candles, key=lambda candle: candle.timestamp)
        if len(ordered) < 2:
            return SimulationMetrics(
                starting_cash=self.starting_cash,
                ending_equity=self.starting_cash,
                total_return=0.0,
                max_drawdown=0.0,
                sharpe=0.0,
                sortino=0.0,
                turnover=0.0,
                trades=(),
                equity_curve=(self.starting_cash,),
            )

        cash = self.starting_cash
        quantity = 0
        curve: list[float] = [self.starting_cash]
        trades: list[SimulatedTrade] = []
        total_turnover = 0.0

        for index in range(len(ordered) - 1):
            signal_bar = ordered[index]
            execution_bar = ordered[index + 1]
            history = ordered[: index + 1]
            signal = strategy.generate(symbol, history)
            equity_at_signal = cash + (quantity * signal_bar.close)
            desired_qty = floor((equity_at_signal * signal.target_weight) / execution_bar.open)
            delta = desired_qty - quantity

            if delta > 0:
                unit_price = execution_bar.open
                requested_notional = delta * unit_price
                estimated_costs = self.costs.cost(requested_notional, is_buy=True)
                max_affordable = floor(max(0.0, cash - estimated_costs) / unit_price)
                fill_qty = min(delta, max_affordable)
                if fill_qty > 0:
                    notional = fill_qty * unit_price
                    costs = self.costs.cost(notional, is_buy=True)
                    cash -= notional + costs
                    quantity += fill_qty
                    total_turnover += notional
                    trades.append(
                        SimulatedTrade(
                            signal_at=signal_bar.timestamp,
                            executed_at=execution_bar.timestamp,
                            symbol=symbol,
                            side="BUY",
                            quantity=fill_qty,
                            price=unit_price,
                            costs=costs,
                        )
                    )
            elif delta < 0:
                fill_qty = min(-delta, quantity)
                if fill_qty > 0:
                    unit_price = execution_bar.open
                    notional = fill_qty * unit_price
                    costs = self.costs.cost(notional, is_buy=False)
                    cash += notional - costs
                    quantity -= fill_qty
                    total_turnover += notional
                    trades.append(
                        SimulatedTrade(
                            signal_at=signal_bar.timestamp,
                            executed_at=execution_bar.timestamp,
                            symbol=symbol,
                            side="SELL",
                            quantity=fill_qty,
                            price=unit_price,
                            costs=costs,
                        )
                    )

            curve.append(cash + (quantity * execution_bar.close))

        ending_equity = curve[-1]
        returns = [
            (curve[index] / curve[index - 1]) - 1
            for index in range(1, len(curve))
            if curve[index - 1] > 0
        ]
        volatility = pstdev(returns) if len(returns) > 1 else 0.0
        sharpe = (mean(returns) / volatility) * sqrt(252) if volatility > 0 else 0.0
        negative = [value for value in returns if value < 0]
        downside = pstdev(negative) if len(negative) > 1 else 0.0
        sortino = (mean(returns) / downside) * sqrt(252) if downside > 0 else 0.0

        peak = self.starting_cash
        max_drawdown = 0.0
        for value in curve:
            peak = max(peak, value)
            if peak > 0:
                max_drawdown = min(max_drawdown, (value / peak) - 1)

        return SimulationMetrics(
            starting_cash=self.starting_cash,
            ending_equity=ending_equity,
            total_return=(ending_equity / self.starting_cash) - 1,
            max_drawdown=max_drawdown,
            sharpe=sharpe,
            sortino=sortino,
            turnover=total_turnover,
            trades=tuple(trades),
            equity_curve=tuple(curve),
        )
