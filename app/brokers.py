from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.models import OrderPlan, Position, Product, Side


@dataclass(frozen=True)
class ExecutionResult:
    order_id: str
    status: str
    filled_quantity: int
    average_price: float


class Broker(Protocol):
    def get_cash(self) -> float: ...
    def get_positions(self) -> list[Position]: ...
    def place_order(self, plan: OrderPlan) -> ExecutionResult: ...


class PaperBroker:
    """Simple deterministic paper broker for foundation tests.

    V1 fills approved limit plans immediately at their limit price. A later
    simulated-exchange layer will add OHLC/tick-aware fills, slippage, latency,
    partial fills and rejections.
    """

    def __init__(self, starting_cash: float) -> None:
        if starting_cash <= 0:
            raise ValueError("starting_cash must be positive")
        self._cash = starting_cash
        self._positions: dict[tuple[str, Product], Position] = {}
        self._order_sequence = 0

    def get_cash(self) -> float:
        return self._cash

    def get_positions(self) -> list[Position]:
        return list(self._positions.values())

    def place_order(self, plan: OrderPlan) -> ExecutionResult:
        if plan.limit_price is None:
            raise ValueError("PaperBroker V1 requires a limit price")
        price = plan.limit_price
        notional = price * plan.quantity
        key = (plan.symbol, plan.product)
        existing = self._positions.get(key)
        current_qty = existing.quantity if existing else 0
        current_avg = existing.average_price if existing else price

        if plan.side == Side.BUY:
            if notional > self._cash:
                raise ValueError("Insufficient paper cash")
            new_qty = current_qty + plan.quantity
            new_avg = ((current_qty * current_avg) + notional) / new_qty
            self._cash -= notional
            self._positions[key] = Position(
                symbol=plan.symbol,
                quantity=new_qty,
                average_price=new_avg,
                product=plan.product,
            )
        elif plan.side == Side.SELL:
            if existing is None or current_qty < plan.quantity:
                raise ValueError("Cannot sell more than the paper position")
            new_qty = current_qty - plan.quantity
            self._cash += notional
            if new_qty == 0:
                del self._positions[key]
            else:
                self._positions[key] = existing.model_copy(update={"quantity": new_qty})
        else:
            raise ValueError("HOLD is not executable")

        self._order_sequence += 1
        return ExecutionResult(
            order_id=f"paper-{self._order_sequence}",
            status="FILLED",
            filled_quantity=plan.quantity,
            average_price=price,
        )
