from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import floor

from app.models import OrderPlan, Quote, RiskDecision, Side, TradeIntent


@dataclass(frozen=True)
class PortfolioSnapshot:
    cash: float
    equity: float
    open_positions: int
    daily_pnl: float = 0.0


@dataclass(frozen=True)
class RiskLimits:
    max_position_pct: float = 0.05
    max_daily_loss_pct: float = 0.01
    max_open_positions: int = 10
    max_quote_age_seconds: int = 15


class RiskEngine:
    """Deterministic gate between AI intent and execution."""

    def __init__(self, limits: RiskLimits) -> None:
        self.limits = limits

    def evaluate(
        self,
        intent: TradeIntent,
        quote: Quote,
        portfolio: PortfolioSnapshot,
    ) -> RiskDecision:
        if intent.side == Side.HOLD:
            return RiskDecision(approved=False, reason="HOLD requires no broker order")

        now = datetime.now(timezone.utc)
        quote_age = (now - quote.as_of.astimezone(timezone.utc)).total_seconds()
        if quote_age > self.limits.max_quote_age_seconds:
            return RiskDecision(approved=False, reason="Quote is stale")

        if quote.symbol != intent.symbol:
            return RiskDecision(approved=False, reason="Quote symbol does not match intent")

        daily_loss_limit = portfolio.equity * self.limits.max_daily_loss_pct
        if portfolio.daily_pnl <= -daily_loss_limit:
            return RiskDecision(approved=False, reason="Daily loss limit reached")

        if portfolio.open_positions >= self.limits.max_open_positions and intent.side == Side.BUY:
            return RiskDecision(approved=False, reason="Maximum open positions reached")

        requested_notional = portfolio.equity * intent.target_allocation_pct
        max_notional = portfolio.equity * self.limits.max_position_pct
        notional = min(requested_notional, max_notional, portfolio.cash)
        quantity = floor(notional / quote.last_price)

        if quantity <= 0:
            return RiskDecision(approved=False, reason="Insufficient capital for one share")

        if intent.side == Side.BUY and intent.entry_max is not None and quote.last_price > intent.entry_max:
            return RiskDecision(approved=False, reason="Price exceeds allowed entry range")
        if intent.side == Side.BUY and intent.entry_min is not None and quote.last_price < intent.entry_min:
            return RiskDecision(approved=False, reason="Price is below allowed entry range")

        plan = OrderPlan(
            intent_id=f"{intent.thesis_id}:{int(intent.decision_at.timestamp())}",
            symbol=intent.symbol,
            side=intent.side,
            product=intent.product,
            quantity=quantity,
            limit_price=quote.last_price,
            stop_price=intent.stop_price,
            target_price=intent.target_price,
        )
        return RiskDecision(approved=True, reason="Approved by deterministic risk rules", order_plan=plan)
