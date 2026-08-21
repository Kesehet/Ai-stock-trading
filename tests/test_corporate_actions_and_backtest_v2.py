from datetime import UTC, datetime, timedelta

from app.backtest_v2 import NextBarBacktester
from app.corporate_actions import CorporateAction, adjust_candles
from app.market_data import Candle
from app.strategies import BuyAndHoldStrategy


def _bar(day: int, open_price: float, close: float) -> Candle:
    timestamp = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=day)
    high = max(open_price, close) + 1
    low = min(open_price, close) - 1
    return Candle("TCS", timestamp, open_price, high, low, close, 1_000)


def test_split_adjusts_pre_action_price_and_volume() -> None:
    before = _bar(0, 200, 200)
    action_at = datetime(2026, 1, 2, tzinfo=UTC)
    action = CorporateAction.split("TCS", action_at, old_face_value=2, new_face_value=1)

    adjusted = adjust_candles([before], [action])[0]

    assert adjusted.close == 100
    assert adjusted.volume == 2_000


def test_next_bar_backtester_executes_after_signal_bar() -> None:
    candles = [
        _bar(0, 100, 100),
        _bar(1, 110, 112),
        _bar(2, 113, 115),
    ]
    result = NextBarBacktester(starting_cash=100_000).run(
        "TCS",
        candles,
        BuyAndHoldStrategy(),
    )

    assert result.trades
    first = result.trades[0]
    assert first.signal_at == candles[0].timestamp
    assert first.executed_at == candles[1].timestamp
    assert first.price == 110
    assert result.turnover > 0
