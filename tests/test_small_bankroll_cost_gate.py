from datetime import UTC, datetime

from app.models import Product, Quote, Side, TradeIntent
from app.risk import PortfolioSnapshot, RiskEngine, RiskLimits


def _buy_intent(
    *,
    now: datetime,
    product: Product,
    price: float,
    stop: float,
    target: float,
) -> tuple[TradeIntent, Quote]:
    intent = TradeIntent(
        symbol="SMALLCAP",
        side=Side.BUY,
        product=product,
        thesis_id="cost-test",
        strategy_id="small-bankroll-test",
        target_allocation_pct=0.025,
        stop_price=stop,
        target_price=target,
        confidence=0.8,
        horizon="short-term",
        decision_at=now,
        data_cutoff_at=now,
    )
    return intent, Quote(symbol="SMALLCAP", last_price=price, as_of=now)


def test_one_share_delivery_trade_is_rejected_when_dp_fee_erases_target_edge() -> None:
    now = datetime(2026, 9, 2, 7, 30, tzinfo=UTC)
    risk = RiskEngine(RiskLimits())
    intent, quote = _buy_intent(
        now=now,
        product=Product.DELIVERY,
        price=64.0,
        stop=62.0,
        target=68.0,
    )
    portfolio = PortfolioSnapshot(cash=500.0, equity=500.0, open_positions=0)

    decision = risk.evaluate(intent, quote, portfolio, now=now)

    assert decision.approved is False
    assert "charges" in decision.reason.lower() or "cost-adjusted" in decision.reason.lower()


def test_delivery_trade_can_pass_when_target_clears_dp_fee_and_reward_risk() -> None:
    now = datetime(2026, 9, 2, 7, 30, tzinfo=UTC)
    risk = RiskEngine(RiskLimits())
    intent, quote = _buy_intent(
        now=now,
        product=Product.DELIVERY,
        price=100.0,
        stop=95.0,
        target=155.0,
    )
    portfolio = PortfolioSnapshot(cash=500.0, equity=500.0, open_positions=0)

    decision = risk.evaluate(intent, quote, portfolio, now=now)

    assert decision.approved is True
    assert decision.order_plan is not None
    assert decision.order_plan.quantity == 1


def test_intraday_trade_does_not_pay_future_delivery_dp_fee() -> None:
    now = datetime(2026, 9, 2, 7, 30, tzinfo=UTC)
    risk = RiskEngine(RiskLimits())
    intent, quote = _buy_intent(
        now=now,
        product=Product.INTRADAY,
        price=64.0,
        stop=62.0,
        target=68.0,
    )
    portfolio = PortfolioSnapshot(cash=500.0, equity=500.0, open_positions=0)

    decision = risk.evaluate(intent, quote, portfolio, now=now)

    assert decision.approved is True
    assert decision.order_plan is not None
    assert decision.order_plan.quantity == 1
