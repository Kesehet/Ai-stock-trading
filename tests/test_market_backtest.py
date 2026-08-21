from datetime import UTC, datetime, timedelta

from app.backtest import Backtester, CostModel
from app.instruments import InstrumentMaster
from app.market_data import Candle, HistoricalDataStore
from app.strategies import BuyAndHoldStrategy, MomentumStrategy


def _candles(count: int = 30, rising: bool = True) -> list[Candle]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    values: list[Candle] = []
    for index in range(count):
        price = 100.0 + index if rising else 130.0 - index
        values.append(
            Candle(
                symbol="TCS",
                timestamp=start + timedelta(days=index),
                open=price,
                high=price + 1,
                low=price - 1,
                close=price,
                volume=1_000_000,
            )
        )
    return values


def test_instrument_master_resolves_symbol_name_and_isin() -> None:
    master = InstrumentMaster.from_csv(
        "exchange,symbol,name,isin,instrument_id,sector\n"
        "NSE,TCS,Tata Consultancy Services Limited,INE467B01029,NSE:INE467B01029,IT\n"
    )

    assert master.require("TCS").isin == "INE467B01029"
    assert master.require("INE467B01029").symbol == "TCS"
    assert master.require("Tata Consultancy Services Limited").symbol == "TCS"


def test_historical_store_never_returns_future_candles() -> None:
    candles = _candles(5)
    store = HistoricalDataStore(candles)
    cutoff = candles[2].timestamp

    visible = store.as_of("TCS", cutoff)

    assert len(visible) == 3
    assert visible[-1].timestamp == cutoff


def test_momentum_strategy_waits_for_history_and_exits_negative_momentum() -> None:
    strategy = MomentumStrategy(lookback=5)

    assert strategy.generate("TCS", _candles(4)).target_weight == 0.0
    assert strategy.generate("TCS", _candles(5, rising=True)).target_weight == 1.0
    assert strategy.generate("TCS", _candles(5, rising=False)).target_weight == 0.0


def test_backtester_applies_costs_and_produces_metrics() -> None:
    candles = _candles(10)
    backtester = Backtester(
        starting_cash=100_000,
        costs=CostModel(buy_rate=0.001, sell_rate=0.001, slippage_bps=5),
    )

    result = backtester.run("TCS", candles, BuyAndHoldStrategy())

    assert result.trades
    assert result.trades[0].side == "BUY"
    assert result.trades[0].costs > 0
    assert result.ending_equity > 0
    assert result.total_return != 0
    assert result.max_drawdown <= 0
