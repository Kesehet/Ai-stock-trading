from datetime import UTC, datetime, timedelta

from app.fund_engine import AutonomousFundEngine
from app.market_data import Candle
from app.models import Product, Quote, Side, TradeIntent
from app.operations import OperationsStore
from app.persistent_paper import PersistentPaperBroker
from app.universe import UniverseRules


class FakeQuotes:
    def get_quote(self, symbol: str) -> Quote:
        return Quote(symbol=symbol, last_price=130.0, as_of=datetime(2026, 1, 31, tzinfo=UTC))


def test_common_engine_spends_through_injected_paper_broker(tmp_path) -> None:
    broker = PersistentPaperBroker(tmp_path / "paper.sqlite3", starting_cash=100_000)
    operations = OperationsStore(tmp_path / "operations.sqlite3")
    engine = AutonomousFundEngine(
        data_dir=tmp_path,
        broker=broker,
        quote_provider=FakeQuotes(),
        operations=operations,
        explicit_universe=("TCS",),
        universe_rules=UniverseRules(
            candidate_limit=10,
            min_price=20,
            min_history_bars=20,
            min_avg_traded_value=1,
        ),
        ollama_base_url="http://127.0.0.1:1",
        ollama_model="test",
        max_position_pct=0.05,
        max_daily_loss_pct=0.01,
        max_open_positions=10,
    )
    start = datetime(2026, 1, 1, tzinfo=UTC)
    for index in range(30):
        engine.market_data.add(
            Candle(
                symbol="TCS",
                timestamp=start + timedelta(days=index),
                open=100 + index,
                high=101 + index,
                low=99 + index,
                close=100 + index,
                volume=1_000_000,
            )
        )
    decision_time = datetime(2026, 1, 31, tzinfo=UTC)
    engine._history_loaded_through = decision_time.date() - timedelta(days=1)

    def fake_intent(symbol: str, as_of: datetime, product: Product = Product.DELIVERY) -> TradeIntent:
        return TradeIntent(
            symbol=symbol,
            side=Side.BUY,
            product=product,
            thesis_id="parity-test",
            strategy_id="parity-test",
            target_allocation_pct=0.05,
            confidence=0.8,
            horizon="test",
            decision_at=as_of,
            data_cutoff_at=as_of,
        )

    engine.research.trade_intent = fake_intent  # type: ignore[method-assign]
    result = engine.run_cycle(decision_time)

    assert result.orders == 1
    assert broker.get_cash() < 100_000
    assert broker.get_positions()[0].symbol == "TCS"
