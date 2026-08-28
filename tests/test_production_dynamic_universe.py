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
    daily_step: float = 1.0,
    recent_volume_multiplier: float = 1.0,
) -> None:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for index in range(25):
        price = start_price + index * daily_step
        candle_volume = volume
        if index >= 20:
            candle_volume *= recent_volume_multiplier
        trader.market_data.add(
            Candle(
                symbol=symbol,
                timestamp=base + timedelta(days=index),
                open=price,
                high=price + 1,
                low=max(0.01, price - 1),
                close=price,
                volume=candle_volume,
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


def test_opportunity_strength_can_outrank_raw_mega_cap_liquidity(tmp_path) -> None:
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

    # MEGACAP trades far more rupees but is nearly flat. MOVER is still highly
    # liquid and has stronger multi-horizon momentum plus recent volume expansion.
    _add_series(
        trader,
        "MEGACAP",
        start_price=1000,
        volume=5_000_000,
        daily_step=0.2,
    )
    _add_series(
        trader,
        "MOVER",
        start_price=100,
        volume=1_000_000,
        daily_step=3.0,
        recent_volume_multiplier=2.0,
    )

    ranked = trader._rank_dynamic_universe(datetime(2026, 2, 1, tzinfo=UTC))

    assert ranked.index("MOVER") < ranked.index("MEGACAP")


def test_dynamic_ai_window_rotates_across_screened_pool(tmp_path) -> None:
    settings = Settings(
        data_dir=str(tmp_path),
        trading_watchlist="",
        max_ai_candidates=3,
        decision_interval_seconds=900,
        _env_file=None,
    )
    trader = ProductionAutonomousTrader(settings)
    trader._dynamic_ranked = tuple(f"STOCK{index}" for index in range(10))

    first = datetime(2026, 1, 5, 9, 15, tzinfo=UTC)
    second = first + timedelta(minutes=15)
    first_window = trader._active_dynamic_window(first)
    second_window = trader._active_dynamic_window(second)

    assert len(first_window) == 3
    assert len(second_window) == 3
    assert first_window != second_window
    assert set(first_window).isdisjoint(second_window)

    selection_events = [
        event
        for event in trader.operations.recent_events(10)
        if event["action"] == "CANDIDATES_SELECTED"
    ]
    assert len(selection_events) == 2
