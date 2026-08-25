from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.brokers import PaperBroker
from app.market_data import HistoricalDataStore
from app.models import Product, Quote, TradeIntent
from app.risk import PortfolioSnapshot, RiskEngine


class IntentProvider(Protocol):
    def trade_intent(
        self,
        symbol: str,
        as_of: datetime,
        product: Product = Product.DELIVERY,
    ) -> TradeIntent: ...


@dataclass(frozen=True)
class SimulationStep:
    timestamp: datetime
    intent: TradeIntent
    risk_approved: bool
    risk_reason: str
    order_id: str | None
    cash: float
    equity: float


@dataclass(frozen=True)
class HistoricalSimulationResult:
    starting_cash: float
    ending_equity: float
    steps: tuple[SimulationStep, ...]


class HistoricalSimulator:
    """Runs research -> intent -> risk -> paper execution using a historical clock."""

    def __init__(
        self,
        market_data: HistoricalDataStore,
        risk: RiskEngine,
        starting_cash: float,
    ) -> None:
        self.market_data = market_data
        self.risk = risk
        self.starting_cash = starting_cash

    def _equity(self, broker: PaperBroker, symbol: str, price: float) -> float:
        position_value = sum(
            position.quantity * price
            for position in broker.get_positions()
            if position.symbol == symbol
        )
        return broker.get_cash() + position_value

    def run(
        self,
        symbol: str,
        decision_times: list[datetime],
        agent: IntentProvider,
    ) -> HistoricalSimulationResult:
        broker = PaperBroker(self.starting_cash)
        steps: list[SimulationStep] = []

        for decision_time in sorted(decision_times):
            candle = self.market_data.latest_as_of(symbol, decision_time)
            if candle is None:
                continue
            intent = agent.trade_intent(symbol, decision_time)
            equity = self._equity(broker, symbol, candle.close)
            portfolio = PortfolioSnapshot(
                cash=broker.get_cash(),
                equity=equity,
                open_positions=len(broker.get_positions()),
            )
            quote = Quote(symbol=symbol, last_price=candle.close, as_of=decision_time)
            decision = self.risk.evaluate(intent, quote, portfolio, now=decision_time)
            order_id: str | None = None
            if decision.approved and decision.order_plan is not None:
                execution = broker.place_order(decision.order_plan)
                order_id = execution.order_id
            ending_step_equity = self._equity(broker, symbol, candle.close)
            steps.append(
                SimulationStep(
                    timestamp=decision_time,
                    intent=intent,
                    risk_approved=decision.approved,
                    risk_reason=decision.reason,
                    order_id=order_id,
                    cash=broker.get_cash(),
                    equity=ending_step_equity,
                )
            )

        final_price = None
        if decision_times:
            final_candle = self.market_data.latest_as_of(symbol, max(decision_times))
            if final_candle is not None:
                final_price = final_candle.close
        ending_equity = broker.get_cash()
        if final_price is not None:
            ending_equity = self._equity(broker, symbol, final_price)
        return HistoricalSimulationResult(
            starting_cash=self.starting_cash,
            ending_equity=ending_equity,
            steps=tuple(steps),
        )
