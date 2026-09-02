from datetime import UTC, datetime

from app.brokers import PaperBroker
from app.models import Product, Quote, Side, TradeIntent
from app.risk import PortfolioSnapshot, RiskEngine, RiskLimits


def make_intent(**overrides: object) -> TradeIntent:
    now = datetime.now(UTC)
    data = {
        "symbol": "TCS",
        "side": Side.BUY,
        "product": Product.DELIVERY,
        "thesis_id": "thesis-1",
        "strategy_id": "manual-test",
        "target_allocation_pct": 0.10,
        "entry_min": 3000.0,
        "entry_max": 3200.0,
        "stop_price": 2950.0,
        "target_price": 3400.0,
        "confidence": 0.8,
        "horizon": "2-8 weeks",
        "evidence_ids": ("e1",),
        "decision_at": now,
        "data_cutoff_at": now,
    }
    data.update(overrides)
    return TradeIntent.model_validate(data)


def test_risk_caps_ai_requested_allocation_and_paper_executes() -> None:
    quote = Quote(symbol="TCS", last_price=3100.0, as_of=datetime.now(UTC))
    portfolio = PortfolioSnapshot(cash=500_000, equity=500_000, open_positions=0)
    engine = RiskEngine(RiskLimits(max_position_pct=0.05))

    decision = engine.evaluate(make_intent(), quote, portfolio)

    assert decision.approved is True
    assert decision.order_plan is not None
    assert decision.order_plan.quantity == 8

    broker = PaperBroker(starting_cash=500_000)
    result = broker.place_order(decision.order_plan)

    assert result.status == "FILLED"
    assert result.filled_quantity == 8
    assert broker.get_cash() == 475_200
    assert broker.get_positions()[0].quantity == 8


def test_daily_loss_limit_blocks_trade() -> None:
    quote = Quote(symbol="TCS", last_price=3100.0, as_of=datetime.now(UTC))
    portfolio = PortfolioSnapshot(
        cash=500_000,
        equity=500_000,
        open_positions=0,
        daily_pnl=-5_000,
    )
    engine = RiskEngine(RiskLimits(max_daily_loss_pct=0.01))

    decision = engine.evaluate(make_intent(), quote, portfolio)

    assert decision.approved is False
    assert decision.reason == "Daily loss limit reached"


def test_entry_range_blocks_chasing_price() -> None:
    quote = Quote(symbol="TCS", last_price=3250.0, as_of=datetime.now(UTC))
    portfolio = PortfolioSnapshot(cash=500_000, equity=500_000, open_positions=0)
    engine = RiskEngine(RiskLimits())

    decision = engine.evaluate(make_intent(), quote, portfolio)

    assert decision.approved is False
    assert decision.reason == "Price exceeds allowed entry range"


def test_defined_stop_caps_position_by_equity_at_risk() -> None:
    now = datetime.now(UTC)
    quote = Quote(symbol="TCS", last_price=100.0, as_of=now)
    portfolio = PortfolioSnapshot(cash=100_000, equity=100_000, open_positions=0)
    engine = RiskEngine(
        RiskLimits(max_position_pct=0.05, max_trade_risk_pct=0.0025)
    )

    decision = engine.evaluate(
        make_intent(
            target_allocation_pct=0.05,
            entry_min=None,
            entry_max=None,
            stop_price=90.0,
            target_price=120.0,
            decision_at=now,
            data_cutoff_at=now,
        ),
        quote,
        portfolio,
        now=now,
    )

    assert decision.approved is True
    assert decision.order_plan is not None
    assert decision.order_plan.quantity == 25


def test_weak_reward_to_risk_is_rejected() -> None:
    now = datetime.now(UTC)
    quote = Quote(symbol="TCS", last_price=100.0, as_of=now)
    portfolio = PortfolioSnapshot(cash=100_000, equity=100_000, open_positions=0)
    engine = RiskEngine(RiskLimits(min_reward_risk=1.5))

    decision = engine.evaluate(
        make_intent(
            entry_min=None,
            entry_max=None,
            stop_price=95.0,
            target_price=106.0,
            decision_at=now,
            data_cutoff_at=now,
        ),
        quote,
        portfolio,
        now=now,
    )

    assert decision.approved is False
    assert "reward" in decision.reason.lower()


def test_tiny_account_can_buy_one_share_within_hard_risk_limits() -> None:
    now = datetime.now(UTC)
    quote = Quote(symbol="CHEAP", last_price=100.0, as_of=now)
    portfolio = PortfolioSnapshot(cash=500.0, equity=500.0, open_positions=0)
    engine = RiskEngine(RiskLimits())

    decision = engine.evaluate(
        make_intent(
            symbol="CHEAP",
            target_allocation_pct=0.05,
            entry_min=None,
            entry_max=None,
            stop_price=95.0,
            target_price=155.0,
            decision_at=now,
            data_cutoff_at=now,
        ),
        quote,
        portfolio,
        now=now,
    )

    assert decision.approved is True
    assert decision.order_plan is not None
    assert decision.order_plan.quantity == 1


def test_tiny_account_does_not_amplify_allocation_without_defined_stop() -> None:
    now = datetime.now(UTC)
    quote = Quote(symbol="CHEAP", last_price=87.0, as_of=now)
    portfolio = PortfolioSnapshot(cash=500.0, equity=500.0, open_positions=0)
    engine = RiskEngine(RiskLimits())

    decision = engine.evaluate(
        make_intent(
            symbol="CHEAP",
            target_allocation_pct=0.025,
            entry_min=None,
            entry_max=None,
            stop_price=None,
            target_price=None,
            decision_at=now,
            data_cutoff_at=now,
        ),
        quote,
        portfolio,
        now=now,
    )

    assert decision.approved is False
    assert decision.reason == "Insufficient capital or risk budget"


def test_tiny_account_rejects_one_share_when_stop_risk_exceeds_budget() -> None:
    now = datetime.now(UTC)
    quote = Quote(symbol="CHEAP", last_price=100.0, as_of=now)
    portfolio = PortfolioSnapshot(cash=500.0, equity=500.0, open_positions=0)
    engine = RiskEngine(RiskLimits(max_trade_risk_pct=0.02))

    decision = engine.evaluate(
        make_intent(
            symbol="CHEAP",
            target_allocation_pct=0.025,
            entry_min=None,
            entry_max=None,
            stop_price=85.0,
            target_price=125.0,
            decision_at=now,
            data_cutoff_at=now,
        ),
        quote,
        portfolio,
        now=now,
    )

    assert decision.approved is False
    assert decision.reason == "Insufficient capital or risk budget"


def test_tiny_account_does_not_override_position_cap_for_expensive_share() -> None:
    now = datetime.now(UTC)
    quote = Quote(symbol="EXPENSIVE", last_price=300.0, as_of=now)
    portfolio = PortfolioSnapshot(cash=500.0, equity=500.0, open_positions=0)
    engine = RiskEngine(RiskLimits())

    decision = engine.evaluate(
        make_intent(
            symbol="EXPENSIVE",
            target_allocation_pct=0.05,
            entry_min=None,
            entry_max=None,
            stop_price=294.0,
            target_price=312.0,
            decision_at=now,
            data_cutoff_at=now,
        ),
        quote,
        portfolio,
        now=now,
    )

    assert decision.approved is False
    assert decision.reason == "Insufficient capital or risk budget"
