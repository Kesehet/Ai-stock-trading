from datetime import UTC, datetime

from app.models import Product, Quote, Side, TradeIntent
from app.risk import PortfolioSnapshot, RiskEngine, RiskLimits


def _intent(*, allocation: float, stop: float, target: float) -> TradeIntent:
    now = datetime(2026, 9, 3, 7, 0, tzinfo=UTC)
    return TradeIntent(
        symbol="MOSCHIP",
        side=Side.BUY,
        product=Product.INTRADAY,
        thesis_id="granularity-test",
        strategy_id="test",
        target_allocation_pct=allocation,
        entry_min=1,
        entry_max=500,
        stop_price=stop,
        target_price=target,
        confidence=0.75,
        horizon="intraday",
        decision_at=now,
        data_cutoff_at=now,
    )


def _quote(price: float) -> Quote:
    now = datetime(2026, 9, 3, 7, 0, tzinfo=UTC)
    return Quote(symbol="MOSCHIP", last_price=price, as_of=now)


def test_rejects_extreme_one_share_allocation_overshoot() -> None:
    engine = RiskEngine(RiskLimits(max_whole_share_allocation_multiple=2.0))
    portfolio = PortfolioSnapshot(cash=466.0, equity=466.0, open_positions=0)

    decision = engine.evaluate(
        _intent(allocation=0.025, stop=205.0, target=235.0),
        _quote(215.0),
        portfolio,
        now=datetime(2026, 9, 3, 7, 0, tzinfo=UTC),
    )

    assert not decision.approved
    assert decision.order_plan is None
    assert "whole-share" in decision.reason


def test_allows_modest_one_share_allocation_overshoot() -> None:
    engine = RiskEngine(RiskLimits(max_whole_share_allocation_multiple=2.0))
    portfolio = PortfolioSnapshot(cash=500.0, equity=500.0, open_positions=0)

    decision = engine.evaluate(
        _intent(allocation=0.25, stop=145.0, target=170.0),
        _quote(150.0),
        portfolio,
        now=datetime(2026, 9, 3, 7, 0, tzinfo=UTC),
    )

    assert decision.approved
    assert decision.order_plan is not None
    assert decision.order_plan.quantity == 1
