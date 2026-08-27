from datetime import UTC, datetime, timedelta

from app.config import Settings
from app.market_data import Candle, HistoricalDataStore
from app.universe import DynamicNSEUniverse, UniverseRules


def _series(symbol: str, *, start: float, volume: float) -> list[Candle]:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    return [
        Candle(
            symbol=symbol,
            timestamp=base + timedelta(days=index),
            open=start + index,
            high=start + index + 1,
            low=start + index - 1,
            close=start + index,
            volume=volume,
        )
        for index in range(30)
    ]


def test_empty_universe_is_the_default_dynamic_mode() -> None:
    settings = Settings(_env_file=None)
    assert settings.paper_universe == ()


def test_explicit_override_is_screened_not_blindly_traded() -> None:
    store = HistoricalDataStore(
        [
            *_series("LIQUID", start=100.0, volume=1_000_000),
            *_series("ILLIQUID", start=100.0, volume=1_000),
            *_series("PENNY", start=2.0, volume=10_000_000),
        ]
    )
    selector = DynamicNSEUniverse(
        store,
        UniverseRules(
            candidate_limit=10,
            min_price=20.0,
            min_history_bars=20,
            min_avg_traded_value=50_000_000.0,
        ),
        explicit_override=("LIQUID", "ILLIQUID", "PENNY"),
    )
    selected = selector.select(datetime(2026, 2, 1, tzinfo=UTC))
    assert [candidate.symbol for candidate in selected] == ["LIQUID"]


def test_candidate_limit_applies_after_full_screening() -> None:
    store = HistoricalDataStore(
        [
            *_series("AAA", start=100.0, volume=1_000_000),
            *_series("BBB", start=100.0, volume=2_000_000),
            *_series("CCC", start=100.0, volume=3_000_000),
        ]
    )
    selector = DynamicNSEUniverse(
        store,
        UniverseRules(
            candidate_limit=2,
            min_price=20.0,
            min_history_bars=20,
            min_avg_traded_value=1.0,
        ),
        explicit_override=("AAA", "BBB", "CCC"),
    )
    selected = selector.select(datetime(2026, 2, 1, tzinfo=UTC))
    assert len(selected) == 2
    assert {candidate.symbol for candidate in selected} == {"BBB", "CCC"}
