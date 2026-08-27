from datetime import UTC, datetime, timedelta

from app.market_data import Candle
from app.models import Product, Quote, Side, TradeIntent
from app.operations import OperationsStore
from app.paper_fund import AutonomousPaperFund


class FakeQuotes:
    def get_quote(self, symbol: str) -> Quote:
        return Quote(symbol=symbol, last_price=100.0, as_of=datetime.now(UTC))


class AlwaysBuyResearch:
    def trade_intent(
        self,
        symbol: str,
        as_of: datetime,
        product: Product = Product.DELIVERY,
    ) -> TradeIntent:
        return TradeIntent(
            symbol=symbol,
            side=Side.BUY,
            product=product,
            thesis_id=f"test:{symbol}:{int(as_of.timestamp())}",
            strategy_id="test_buy",
            target_allocation_pct=0.03,
            confidence=0.8,
            horizon="test",
            evidence_ids=(),
            decision_at=as_of,
            data_cutoff_at=as_of,
        )


def _fund(tmp_path) -> AutonomousPaperFund:
    operations = OperationsStore(tmp_path / "operations.sqlite3")
    fund = AutonomousPaperFund(
        data_dir=tmp_path,
        starting_cash=100_000,
        universe=("TCS",),
        quote_provider=FakeQuotes(),
        operations=operations,
        ollama_base_url="http://127.0.0.1:1",
        ollama_model="unused",
        max_position_pct=0.05,
        max_daily_loss_pct=0.01,
        max_open_positions=10,
        history_days=30,
        fallback_momentum=True,
        fallback_target_pct=0.03,
    )
    now = datetime.now(UTC)
    for index in range(25):
        price = 80.0 + index
        fund.market_data.add(
            Candle(
                symbol="TCS",
                timestamp=now - timedelta(days=25 - index),
                open=price,
                high=price + 1,
                low=price - 1,
                close=price,
                volume=1_000_000,
            )
        )
    fund._history_loaded_through = now.date() - timedelta(days=1)
    fund.research = AlwaysBuyResearch()  # type: ignore[assignment]
    return fund


def test_paper_cycle_spends_cash_and_persists_position(tmp_path) -> None:
    fund = _fund(tmp_path)
    before = fund.broker.get_cash()

    result = fund.run_cycle(datetime.now(UTC))

    assert result.orders == 1
    assert fund.broker.get_cash() < before
    positions = fund.broker.get_positions()
    assert len(positions) == 1
    assert positions[0].symbol == "TCS"

    restarted = _fund(tmp_path)
    assert restarted.broker.get_cash() == fund.broker.get_cash()
    assert restarted.broker.get_positions()[0].quantity == positions[0].quantity


def test_second_cycle_does_not_accumulate_same_symbol_again(tmp_path) -> None:
    fund = _fund(tmp_path)
    now = datetime.now(UTC)
    first = fund.run_cycle(now)
    cash_after_first = fund.broker.get_cash()

    second = fund.run_cycle(now + timedelta(minutes=15))

    assert first.orders == 1
    assert second.orders == 0
    assert second.holds == 1
    assert fund.broker.get_cash() == cash_after_first
