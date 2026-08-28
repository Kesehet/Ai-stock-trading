from datetime import UTC, datetime

from app.models import Position, Product, Quote, Side, TradeIntent
from app.risk import PortfolioSnapshot, RiskEngine, RiskLimits


def _intent(*, stop: float, target: float, allocation: float = 0.05) -> TradeIntent:
    now = datetime(2026, 8, 28, 9, 30, tzinfo=UTC)
    return TradeIntent(
        symbol="TEST",
        side=Side.BUY,
        product=Product.DELIVERY,
        thesis_id="thesis-test",
        strategy_id="shared-engine-test",
        target_allocation_pct=allocation,
        stop_price=stop,
        target_price=target,
        confidence=0.8,
        horizon="short-term",
        decision_at=now,
        data_cutoff_at=now,
    )


def _quote(price: float) -> Quote:
    return Quote(
        symbol="TEST",
        last_price=price,
        as_of=datetime(2026, 8, 28, 9, 30, tzinfo=UTC),
    )


def _portfolio(*, average_price: float, quantity: int = 50) -> PortfolioSnapshot:
    return PortfolioSnapshot(
        cash=100_000.0,
        equity=500_000.0,
        open_positions=1,
        positions=(
            Position(
                symbol="TEST",
                quantity=quantity,
                average_price=average_price,
                product=Product.DELIVERY,
            ),
        ),
    )


def test_average_down_rejects_target_below_blended_cost() -> None:
    engine = RiskEngine(
        RiskLimits(
            max_position_pct=0.10,
            min_buy_confidence=0.55,
            max_trade_risk_pct=0.10,
            min_reward_risk=1.5,
        )
    )
    decision = engine.evaluate(
        _intent(stop=91.0, target=94.0, allocation=0.012),
        _quote(92.0),
        _portfolio(average_price=100.0),
        now=datetime(2026, 8, 28, 9, 30, tzinfo=UTC),
    )

    assert not decision.approved
    assert decision.reason == "Target does not clear blended position cost"


def test_average_down_uses_existing_cost_basis_for_risk_budget() -> None:
    engine = RiskEngine(
        RiskLimits(
            max_position_pct=0.10,
            min_buy_confidence=0.55,
            max_trade_risk_pct=0.0025,
            min_reward_risk=1.5,
        )
    )
    decision = engine.evaluate(
        _intent(stop=90.0, target=120.0),
        _quote(95.0),
        _portfolio(average_price=110.0, quantity=100),
        now=datetime(2026, 8, 28, 9, 30, tzinfo=UTC),
    )

    assert not decision.approved
    assert decision.reason == "Insufficient capital or risk budget"


def test_add_is_allowed_when_blended_reward_risk_remains_sound() -> None:
    engine = RiskEngine(
        RiskLimits(
            max_position_pct=0.10,
            min_buy_confidence=0.55,
            max_trade_risk_pct=0.02,
            min_reward_risk=1.5,
        )
    )
    decision = engine.evaluate(
        _intent(stop=90.0, target=130.0),
        _quote(105.0),
        _portfolio(average_price=100.0, quantity=50),
        now=datetime(2026, 8, 28, 9, 30, tzinfo=UTC),
    )

    assert decision.approved
    assert decision.order_plan is not None
    assert decision.order_plan.quantity > 0
