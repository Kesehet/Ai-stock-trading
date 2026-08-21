from datetime import datetime, timezone

from app.brokers import PaperBroker
from app.models import Product, Quote, Side, TradeIntent
from app.risk import PortfolioSnapshot, RiskEngine, RiskLimits


def make_intent(**overrides: object) -> TradeIntent:
    now = datetime.now(timezone.utc)
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
    quote = Quote(symbol="TCS", last_price=3100.0, as_of=datetime.now(timezone.utc))
    portfolio = PortfolioSnapshot(cash=500_000, equity=500_000, open_positions=0)
    engine = RiskEngine(RiskLimits(max_position_pct=0.05))

    decision = engine.evaluate(make_intent(), quote, portfolio)

    assert decision.approved is True
    assert decision.order_plan is not None
    # AI requested 10%, but the deterministic 5% cap gives floor(25,000 / 3,100) = 8.
    assert decision.order_plan.quantity == 8

    broker = PaperBroker(starting_cash=500_000)
    result = broker.place_order(decision.order_plan)

    assert result.status == "FILLED"
    assert result.filled_quantity == 8
    assert broker.get_cash() == 475_200
    assert broker.get_positions()[0].quantity == 8


def test_daily_loss_limit_blocks_trade() -> None:
    quote = Quote(symbol="TCS", last_price=3100.0, as_of=datetime.now(timezone.utc))
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
    quote = Quote(symbol="TCS", last_price=3250.0, as_of=datetime.now(timezone.utc))
    portfolio = PortfolioSnapshot(cash=500_000, equity=500_000, open_positions=0)
    engine = RiskEngine(RiskLimits())

    decision = engine.evaluate(make_intent(), quote, portfolio)

    assert decision.approved is False
    assert decision.reason == "Price exceeds allowed entry range"
