from datetime import UTC, datetime

from app.brokers import PaperBroker
from app.models import Product, Quote, Side, TradeIntent
from app.risk import PortfolioSnapshot, RiskEngine, RiskLimits


def main() -> None:
    now = datetime.now(UTC)
    intent = TradeIntent(
        symbol="TCS",
        side=Side.BUY,
        product=Product.DELIVERY,
        thesis_id="demo-thesis",
        strategy_id="demo",
        target_allocation_pct=0.10,
        entry_min=3000,
        entry_max=3200,
        stop_price=2950,
        target_price=3400,
        confidence=0.80,
        horizon="2-8 weeks",
        evidence_ids=("demo-evidence",),
        decision_at=now,
        data_cutoff_at=now,
    )
    quote = Quote(symbol="TCS", last_price=3100, as_of=now)
    portfolio = PortfolioSnapshot(cash=500_000, equity=500_000, open_positions=0)
    risk = RiskEngine(RiskLimits(max_position_pct=0.05))
    decision = risk.evaluate(intent, quote, portfolio)

    print(decision.model_dump_json(indent=2))
    if not decision.approved or decision.order_plan is None:
        return

    broker = PaperBroker(starting_cash=portfolio.cash)
    execution = broker.place_order(decision.order_plan)
    print(execution)
    print("Cash:", broker.get_cash())
    print("Positions:", broker.get_positions())


if __name__ == "__main__":
    main()
