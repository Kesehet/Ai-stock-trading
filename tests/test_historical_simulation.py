from datetime import UTC, datetime, timedelta

from app.market_data import Candle, HistoricalDataStore
from app.models import Product, Side, TradeIntent
from app.risk import RiskEngine, RiskLimits
from app.simulation import HistoricalSimulator


class FakeAgent:
    def __init__(self) -> None:
        self.calls = 0

    def trade_intent(
        self,
        symbol: str,
        as_of: datetime,
        product: Product = Product.DELIVERY,
    ) -> TradeIntent:
        self.calls += 1
        side = Side.BUY if self.calls == 1 else Side.HOLD
        allocation = 0.10 if side == Side.BUY else 0.0
        return TradeIntent(
            symbol=symbol,
            side=side,
            product=product,
            thesis_id=f"fake-{self.calls}",
            strategy_id="fake",
            target_allocation_pct=allocation,
            entry_max=200.0,
            stop_price=90.0 if side == Side.BUY else None,
            target_price=200.0 if side == Side.BUY else None,
            confidence=0.8,
            horizon="test",
            evidence_ids=(),
            decision_at=as_of,
            data_cutoff_at=as_of,
        )


def test_historical_simulator_uses_historical_clock_and_executes() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    candles = [
        Candle(
            symbol="TCS",
            timestamp=start + timedelta(days=index),
            open=100.0 + index,
            high=101.0 + index,
            low=99.0 + index,
            close=100.0 + index,
            volume=1_000_000,
        )
        for index in range(3)
    ]
    simulator = HistoricalSimulator(
        market_data=HistoricalDataStore(candles),
        risk=RiskEngine(RiskLimits(max_position_pct=0.05, max_quote_age_seconds=15)),
        starting_cash=100_000,
    )

    result = simulator.run("TCS", [candle.timestamp for candle in candles], FakeAgent())

    assert len(result.steps) == 3
    assert result.steps[0].risk_approved is True
    assert result.steps[0].order_id == "paper-1"
    assert result.steps[1].risk_approved is False
    assert result.steps[1].risk_reason == "HOLD requires no broker order"
    assert result.ending_equity > 0
