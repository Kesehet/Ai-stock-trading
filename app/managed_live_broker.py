from __future__ import annotations

from datetime import UTC, datetime

from app.brokers import ExecutionResult
from app.live_order_ledger import LiveOrderLedger
from app.models import OrderPlan, Position, Side
from app.zerodha_api import ZerodhaApi


class ManagedLiveBroker:
    """Real Zerodha execution while exposing only bot-owned capital/positions to AI and risk."""

    def __init__(
        self,
        api: ZerodhaApi,
        ledger: LiveOrderLedger,
        starting_cash: float,
        order_timeout_seconds: int = 120,
    ) -> None:
        self.api = api
        self.ledger = ledger
        self.starting_cash = starting_cash
        self.order_timeout_seconds = order_timeout_seconds

    def get_cash(self) -> float:
        virtual_cash = self.ledger.managed_cash(self.starting_cash)
        return min(virtual_cash, max(0.0, self.api.get_cash()))

    def get_positions(self) -> list[Position]:
        return self.ledger.managed_positions()

    def place_order(self, plan: OrderPlan) -> ExecutionResult:
        if plan.side == Side.BUY and plan.limit_price is not None:
            required = plan.limit_price * plan.quantity
            if required > self.api.get_cash():
                raise ValueError("Zerodha account has insufficient available cash")
        if not self.ledger.claim(plan):
            raise ValueError("live intent was already submitted or reserved")
        try:
            execution = self.api.place_order(plan)
        except Exception:
            self.ledger.update(plan.intent_id, status="UNKNOWN")
            raise
        self.ledger.update(
            plan.intent_id,
            broker_order_id=execution.order_id,
            status=execution.status,
            filled_quantity=execution.filled_quantity,
            average_price=execution.average_price if execution.filled_quantity else None,
        )
        return execution

    def reconcile(self, now: datetime | None = None) -> list[tuple[str, str]]:
        current = now or datetime.now(UTC)
        updates: list[tuple[str, str]] = []
        for record in self.ledger.pending():
            if not record.broker_order_id:
                # A send whose acknowledgement is unknown is never retried automatically.
                continue
            status = self.api.order_status(record.broker_order_id)
            if status is None:
                continue
            age = (current.astimezone(UTC) - record.created_at.astimezone(UTC)).total_seconds()
            if (
                status.status in {"OPEN", "SUBMITTED", "VALIDATION PENDING"}
                and status.pending_quantity > 0
                and age >= self.order_timeout_seconds
            ):
                try:
                    self.api.cancel_order(record.broker_order_id)
                    status_name = "CANCEL_REQUESTED"
                except Exception:
                    status_name = status.status
                self.ledger.update(
                    record.intent_id,
                    broker_order_id=status.order_id,
                    status=status_name,
                    filled_quantity=status.filled_quantity,
                    average_price=status.average_price if status.average_price > 0 else None,
                )
                updates.append((record.intent_id, status_name))
                continue
            self.ledger.update(
                record.intent_id,
                broker_order_id=status.order_id,
                status=status.status,
                filled_quantity=status.filled_quantity,
                average_price=status.average_price if status.average_price > 0 else None,
            )
            updates.append((record.intent_id, status.status))
        return updates
