from __future__ import annotations

from dataclasses import dataclass
from math import floor, sqrt
from statistics import mean, pstdev

from app.market_data import Candle
from app.strategies import Strategy


@dataclass(frozen=True)
class CostModel:
    """Configurable cash-equity cost approximation.

    Values are deliberately configuration-driven because Indian brokerage/tax
    schedules change. Keep statutory rates outside LLM control and validate
    them before any production use.
    """

    buy_rate: float = 0.0010
    sell_rate: float = 0.0010
    slippage_bps: float = 5.0

    def cost(self, notional: float, is_buy: bool) -> float:
        rate = self.buy_rate if is_buy else self.sell_rate
        slippage = notional * self.slippage_bps / 10_000
        return (notional * rate) + slippage


@dataclass(frozen=True)
class BacktestTrade:
    timestamp: object
    symbol: str
    side: str
    quantity: int
    price: float
    costs: float


@dataclass(frozen=True)
class BacktestResult:
    starting_cash: float
    ending_equity: float
    total_return: float
    max_drawdown: float
    sharpe: float
    trades: tuple[BacktestTrade, ...]
    equity_curve: tuple[float, ...]


class Backtester:
    """Daily/bar-close target-weight backtester with no future-bar access."""

    def __init__(self, starting_cash: float, costs: CostModel | None = None) -> None:
        if starting_cash <= 0:
            raise ValueError("starting_cash must be positive")
        self.starting_cash = starting_cash
        self.costs = costs or CostModel()

    def run(self, symbol: str, candles: list[Candle], strategy: Strategy) -> BacktestResult:
        ordered = sorted(candles, key=lambda candle: candle.timestamp)
        cash = self.starting_cash
        quantity = 0
        curve: list[float] = []
        trades: list[BacktestTrade] = []

        for index, candle in enumerate(ordered):
            # Strategy can see this candle and prior candles only. Execution is
            # modelled at this bar close; later event-driven versions can shift
            # execution to the next bar open for stricter signal/execution separation.
            history = ordered[: index + 1]
            signal = strategy.generate(symbol, history)
            equity_before = cash + (quantity * candle.close)
            desired_notional = equity_before * signal.target_weight
            desired_qty = floor(desired_notional / candle.close)
            delta = desired_qty - quantity

            if delta > 0:
                notional = delta * candle.close
                costs = self.costs.cost(notional, is_buy=True)
                affordable = cash - costs
                max_delta = floor(max(0.0, affordable) / candle.close)
                delta = min(delta, max_delta)
                if delta > 0:
                    notional = delta * candle.close
                    costs = self.costs.cost(notional, is_buy=True)
                    cash -= notional + costs
                    quantity += delta
                    trades.append(
                        BacktestTrade(candle.timestamp, symbol, "BUY", delta, candle.close, costs)
                    )
            elif delta < 0:
                sell_qty = min(-delta, quantity)
                if sell_qty > 0:
                    notional = sell_qty * candle.close
                    costs = self.costs.cost(notional, is_buy=False)
                    cash += notional - costs
                    quantity -= sell_qty
                    trades.append(
                        BacktestTrade(
                            candle.timestamp,
                            symbol,
                            "SELL",
                            sell_qty,
                            candle.close,
                            costs,
                        )
                    )

            curve.append(cash + (quantity * candle.close))

        ending_equity = curve[-1] if curve else self.starting_cash
        returns = [
            (curve[index] / curve[index - 1]) - 1
            for index in range(1, len(curve))
            if curve[index - 1] > 0
        ]
        sharpe = 0.0
        if len(returns) > 1 and pstdev(returns) > 0:
            sharpe = (mean(returns) / pstdev(returns)) * sqrt(252)

        peak = self.starting_cash
        max_drawdown = 0.0
        for value in curve:
            peak = max(peak, value)
            drawdown = (value / peak) - 1 if peak > 0 else 0.0
            max_drawdown = min(max_drawdown, drawdown)

        total_return = (ending_equity / self.starting_cash) - 1
        return BacktestResult(
            starting_cash=self.starting_cash,
            ending_equity=ending_equity,
            total_return=total_return,
            max_drawdown=max_drawdown,
            sharpe=sharpe,
            trades=tuple(trades),
            equity_curve=tuple(curve),
        )
