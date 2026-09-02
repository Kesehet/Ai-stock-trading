from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from math import floor

from app.costs import ZERODHA_NSE_CASH_2026
from app.models import OrderPlan, Position, Product, Quote, RiskDecision, Side, TradeIntent


@dataclass(frozen=True)
class PortfolioSnapshot:
    cash: float
    equity: float
    open_positions: int
    daily_pnl: float = 0.0
    positions: tuple[Position, ...] = ()


@dataclass(frozen=True)
class RiskLimits:
    max_position_pct: float = 0.50
    max_daily_loss_pct: float = 0.05
    max_open_positions: int = 3
    max_quote_age_seconds: int = 15
    min_buy_confidence: float = 0.60
    max_trade_risk_pct: float = 0.02
    min_reward_risk: float = 1.5
    expected_slippage_bps: float = 5.0


class RiskEngine:
    """Deterministic gate between AI intent and execution."""

    def __init__(self, limits: RiskLimits) -> None:
        self.limits = limits

    def _delivery_cost_adjusted_reward_risk(
        self,
        *,
        quantity: int,
        entry_price: float,
        stop_price: float,
        target_price: float,
    ) -> tuple[float, float, float]:
        """Estimate overnight delivery economics after slippage and statutory costs.

        A DELIVERY position can survive beyond the entry session, so a realistic
        future exit must include the depository-participant sell fee. This matters
        disproportionately for a one-share, roughly ₹500 bankroll.
        """
        slippage = max(0.0, self.limits.expected_slippage_bps) / 10_000.0
        entry_fill = entry_price * (1.0 + slippage)
        target_fill = target_price * (1.0 - slippage)
        stop_fill = stop_price * (1.0 - slippage)

        entry_turnover = entry_fill * quantity
        target_turnover = target_fill * quantity
        stop_turnover = stop_fill * quantity
        entry_cost = ZERODHA_NSE_CASH_2026.charges(
            turnover=entry_turnover,
            side=Side.BUY,
            product=Product.DELIVERY,
        )
        target_exit_cost = ZERODHA_NSE_CASH_2026.charges(
            turnover=target_turnover,
            side=Side.SELL,
            product=Product.DELIVERY,
            include_dp=True,
        )
        stop_exit_cost = ZERODHA_NSE_CASH_2026.charges(
            turnover=stop_turnover,
            side=Side.SELL,
            product=Product.DELIVERY,
            include_dp=True,
        )

        net_reward = (target_fill - entry_fill) * quantity - entry_cost - target_exit_cost
        net_downside = (entry_fill - stop_fill) * quantity + entry_cost + stop_exit_cost
        reward_risk = net_reward / net_downside if net_downside > 0 else 0.0
        return net_reward, net_downside, reward_risk

    def evaluate(
        self,
        intent: TradeIntent,
        quote: Quote,
        portfolio: PortfolioSnapshot,
        now: datetime | None = None,
    ) -> RiskDecision:
        if intent.side == Side.HOLD:
            return RiskDecision(approved=False, reason="HOLD requires no broker order")

        decision_time = now or datetime.now(UTC)
        if decision_time.tzinfo is None:
            raise ValueError("risk decision clock must be timezone-aware")
        quote_age = (decision_time.astimezone(UTC) - quote.as_of.astimezone(UTC)).total_seconds()
        if quote_age < 0:
            return RiskDecision(approved=False, reason="Quote is from the future")
        if quote_age > self.limits.max_quote_age_seconds:
            return RiskDecision(approved=False, reason="Quote is stale")
        if quote.symbol != intent.symbol:
            return RiskDecision(approved=False, reason="Quote symbol does not match intent")

        daily_loss_limit = portfolio.equity * self.limits.max_daily_loss_pct
        if intent.side == Side.BUY and portfolio.daily_pnl <= -daily_loss_limit:
            return RiskDecision(approved=False, reason="Daily loss limit reached")
        if intent.side == Side.BUY and intent.confidence < self.limits.min_buy_confidence:
            return RiskDecision(approved=False, reason="AI confidence is below buy threshold")
        if (
            intent.side == Side.BUY
            and intent.entry_max is not None
            and quote.last_price > intent.entry_max
        ):
            return RiskDecision(approved=False, reason="Price exceeds allowed entry range")
        if (
            intent.side == Side.BUY
            and intent.entry_min is not None
            and quote.last_price < intent.entry_min
        ):
            return RiskDecision(approved=False, reason="Price is below allowed entry range")

        if intent.side == Side.BUY and intent.stop_price is not None:
            if intent.stop_price >= quote.last_price:
                return RiskDecision(approved=False, reason="Buy stop must be below entry price")
        if intent.side == Side.BUY and intent.target_price is not None:
            if intent.target_price <= quote.last_price:
                return RiskDecision(approved=False, reason="Buy target must be above entry price")
        if (
            intent.side == Side.BUY
            and intent.stop_price is not None
            and intent.target_price is not None
        ):
            downside = quote.last_price - intent.stop_price
            upside = intent.target_price - quote.last_price
            reward_risk = upside / downside if downside > 0 else 0.0
            if reward_risk < self.limits.min_reward_risk:
                return RiskDecision(
                    approved=False,
                    reason="Expected reward does not justify defined downside risk",
                )

        matching_positions = [
            position
            for position in portfolio.positions
            if position.symbol == intent.symbol and position.product == intent.product
        ]
        held_quantity = sum(position.quantity for position in matching_positions)
        existing_cost = sum(
            position.quantity * position.average_price for position in matching_positions
        )
        current_value = held_quantity * quote.last_price

        if (
            portfolio.open_positions >= self.limits.max_open_positions
            and intent.side == Side.BUY
            and held_quantity == 0
        ):
            return RiskDecision(approved=False, reason="Maximum open positions reached")

        if intent.side == Side.SELL:
            if held_quantity <= 0:
                return RiskDecision(approved=False, reason="No matching position available to sell")
            desired_remaining = min(
                current_value,
                portfolio.equity * intent.target_allocation_pct,
            )
            sell_notional = max(0.0, current_value - desired_remaining)
            quantity = held_quantity if intent.target_allocation_pct == 0 else floor(
                sell_notional / quote.last_price
            )
            if quantity <= 0:
                return RiskDecision(
                    approved=False,
                    reason="Position is already at or below requested remaining allocation",
                )
            quantity = min(quantity, held_quantity)
        else:
            position_cap = portfolio.equity * self.limits.max_position_pct
            desired_notional = min(
                portfolio.equity * intent.target_allocation_pct,
                position_cap,
            )
            # Whole-share execution makes small percentage allocations impractical in
            # a ₹500-sized account. Permit the one-share override only when a defined
            # stop exists, so the max-trade-risk budget below can actually constrain
            # the rupee loss. This guard is shared by paper and live modes.
            if (
                held_quantity == 0
                and intent.stop_price is not None
                and desired_notional < quote.last_price <= position_cap
                and quote.last_price <= portfolio.cash
            ):
                desired_notional = quote.last_price
            additional_notional = max(0.0, desired_notional - current_value)
            notional = min(additional_notional, portfolio.cash)

            if intent.stop_price is not None:
                risk_per_share = quote.last_price - intent.stop_price
                if risk_per_share > 0:
                    risk_budget = portfolio.equity * self.limits.max_trade_risk_pct
                    existing_defined_risk = sum(
                        position.quantity
                        * max(0.0, position.average_price - intent.stop_price)
                        for position in matching_positions
                    )
                    remaining_risk_budget = max(0.0, risk_budget - existing_defined_risk)
                    risk_fraction = risk_per_share / quote.last_price
                    risk_notional_cap = (
                        remaining_risk_budget / risk_fraction if risk_fraction > 0 else 0.0
                    )
                    notional = min(notional, risk_notional_cap)

            quantity = floor(notional / quote.last_price)
            if quantity <= 0 and current_value >= desired_notional:
                return RiskDecision(
                    approved=False,
                    reason="Position is already at or above target allocation",
                )

        if quantity <= 0:
            return RiskDecision(approved=False, reason="Insufficient capital or risk budget")

        if (
            intent.side == Side.BUY
            and held_quantity == 0
            and intent.product == Product.DELIVERY
            and intent.stop_price is not None
            and intent.target_price is not None
        ):
            net_reward, _, cost_adjusted_reward_risk = (
                self._delivery_cost_adjusted_reward_risk(
                    quantity=quantity,
                    entry_price=quote.last_price,
                    stop_price=intent.stop_price,
                    target_price=intent.target_price,
                )
            )
            if net_reward <= 0:
                return RiskDecision(
                    approved=False,
                    reason="Delivery target does not clear realistic charges and slippage",
                )
            if cost_adjusted_reward_risk < self.limits.min_reward_risk:
                return RiskDecision(
                    approved=False,
                    reason="Cost-adjusted reward does not justify delivery downside risk",
                )

        if intent.side == Side.BUY and held_quantity > 0:
            projected_quantity = held_quantity + quantity
            projected_average = (
                (existing_cost + (quantity * quote.last_price)) / projected_quantity
            )
            if (
                intent.target_price is not None
                and intent.target_price <= projected_average
            ):
                return RiskDecision(
                    approved=False,
                    reason="Target does not clear blended position cost",
                )
            if (
                intent.stop_price is not None
                and intent.target_price is not None
                and intent.stop_price < projected_average
            ):
                blended_downside = projected_average - intent.stop_price
                blended_upside = intent.target_price - projected_average
                blended_reward_risk = (
                    blended_upside / blended_downside if blended_downside > 0 else 0.0
                )
                if blended_reward_risk < self.limits.min_reward_risk:
                    return RiskDecision(
                        approved=False,
                        reason="Expected reward does not justify blended position risk",
                    )

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
        return RiskDecision(
            approved=True,
            reason="Approved by deterministic risk rules",
            order_plan=plan,
        )
