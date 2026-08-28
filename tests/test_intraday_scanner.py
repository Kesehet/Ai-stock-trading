from datetime import UTC, datetime, timedelta

from app.config import Settings
from app.intraday_scanner import IntradayOpportunityScanner
from app.market_data import Candle, HistoricalDataStore
from app.production_trader import ProductionAutonomousTrader
from app.zerodha_api import LiveMarketSnapshot


def _history(symbol: str, base_price: float = 100.0) -> HistoricalDataStore:
    store = HistoricalDataStore()
    start = datetime(2026, 8, 1, tzinfo=UTC)
    for index in range(20):
        price = base_price + index * 0.2
        store.add(
            Candle(
                symbol=symbol,
                timestamp=start + timedelta(days=index),
                open=price,
                high=price + 1.0,
                low=price - 1.0,
                close=price,
                volume=1_000_000,
            )
        )
    return store


def test_live_mover_with_volume_outranks_flat_stock() -> None:
    now = datetime(2026, 8, 20, 5, 0, tzinfo=UTC)
    market = _history("RIPPER")
    for candle in _history("FLAT").as_of("FLAT", now, limit=20):
        market.add(candle)
    scanner = IntradayOpportunityScanner(market)

    snapshots = {
        "RIPPER": LiveMarketSnapshot(
            symbol="RIPPER",
            last_price=112.0,
            open_price=104.0,
            high_price=113.0,
            low_price=103.0,
            previous_close=103.8,
            volume=1_500_000,
            as_of=now,
        ),
        "FLAT": LiveMarketSnapshot(
            symbol="FLAT",
            last_price=104.0,
            open_price=103.9,
            high_price=104.2,
            low_price=103.5,
            previous_close=103.8,
            volume=250_000,
            as_of=now,
        ),
    }

    ranked = scanner.rank(snapshots, now)

    assert ranked[0].symbol == "RIPPER"
    assert ranked[0].score > ranked[1].score
    assert ranked[0].move_pct > 0.07
    assert ranked[0].volume_pace > 1.0


def test_hot_symbol_uses_short_interrupt_cooldown(tmp_path) -> None:
    settings = Settings(
        data_dir=str(tmp_path),
        trading_watchlist="",
        decision_interval_seconds=900,
        intraday_interrupt_cooldown_seconds=300,
        _env_file=None,
    )
    trader = ProductionAutonomousTrader(settings)
    now = datetime(2026, 8, 20, 5, 0, tzinfo=UTC)
    trader._intraday_hot = ("RIPPER",)
    trader.state_store.record_decision("RIPPER", now - timedelta(seconds=301))
    trader.state_store.record_decision("NORMAL", now - timedelta(seconds=301))

    assert trader._decision_due("RIPPER", now) is True
    assert trader._decision_due("NORMAL", now) is False
