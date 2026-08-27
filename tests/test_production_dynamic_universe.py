from datetime import UTC, datetime, timedelta

from app.config import Settings
from app.market_data import Candle
from app.production_trader import ProductionAutonomousTrader


def _add_series(
    trader: ProductionAutonomousTrader,
    symbol: str,
    *,
    start_price: float,
    volume: float,
) -> None:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for index in range(25):
        price = start_price + index
        trader.market_data.add(
            Candle(
                symbol=symbol,
                timestamp=base + timedelta(days=index),
                open=price,
                high=price + 1,
                low=price - 1,
                close=price,
                volume=volume,
            )
        )


def test_empty_watchlist_enables_dynamic_nse_mode(tmp_path) -> None:
    settings = Settings(data_dir=str(tmp_path), trading_watchlist="", _env_file=None)
    assert settings.watchlist == ()
    assert settings.dynamic_universe is True


def test_nonempty_watchlist_is_explicit_override(tmp_path) -> None:
    settings = Settings(
        data_dir=str(tmp_path),
        trading_watchlist="tcs, reliance,TCS",
        _env_file=None,
    )
    assert settings.watchlist == ("TCS", "RELIANCE")
    assert settings.dynamic_universe is False


def test_dynamic_ranking_filters_penny_and_illiquid_names(tmp_path) -> None:
    settings = Settings(
        data_dir=str(tmp_path),
        trading_watchlist="",
        universe_min_price=20,
        universe_min_history_bars=20,
        universe_min_avg_traded_value=50_000_000,
        universe_scan_limit=10,
        _env_file=None,
    )
    trader = ProductionAutonomousTrader(settings)
    _add_series(trader, "LIQUID", start_price=100, volume=1_000_000)
    _add_series(trader, "ILLIQUID", start_price=100, volume=1_000)
    _add_series(trader, "PENNY", start_price=2, volume=10_000_000)

    ranked = trader._rank_dynamic_universe(datetime(2026, 2, 1, tzinfo=UTC))

    assert ranked == ("LIQUID",)
