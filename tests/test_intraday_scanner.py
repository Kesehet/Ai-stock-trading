import json
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


def _snapshot(symbol: str, price: float, now: datetime) -> LiveMarketSnapshot:
    return LiveMarketSnapshot(
        symbol=symbol,
        last_price=price,
        open_price=104.0,
        high_price=max(113.0, price),
        low_price=103.0,
        previous_close=103.8,
        volume=1_500_000,
        as_of=now,
    )


def test_live_mover_with_volume_outranks_flat_stock() -> None:
    now = datetime(2026, 8, 20, 5, 0, tzinfo=UTC)
    market = _history("RIPPER")
    for candle in _history("FLAT").as_of("FLAT", now, limit=20):
        market.add(candle)
    scanner = IntradayOpportunityScanner(market)

    snapshots = {
        "RIPPER": _snapshot("RIPPER", 112.0, now),
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


def test_acceleration_survives_scanner_restart(tmp_path) -> None:
    market = _history("RIPPER")
    state_path = tmp_path / "intraday-scanner-state.json"
    first_time = datetime(2026, 8, 20, 5, 0, tzinfo=UTC)
    second_time = first_time + timedelta(minutes=1)

    first = IntradayOpportunityScanner(market, state_path)
    first.rank({"RIPPER": _snapshot("RIPPER", 110.0, first_time)}, first_time)

    restarted = IntradayOpportunityScanner(market, state_path)
    ranked = restarted.rank(
        {"RIPPER": _snapshot("RIPPER", 111.0, second_time)},
        second_time,
    )

    assert ranked[0].acceleration_pct > 0.009
    assert ranked[0].acceleration_pct < 0.01


def test_scanner_persists_entry_quality_history(tmp_path) -> None:
    market = _history("RIPPER")
    state_path = tmp_path / "intraday-scanner-state.json"
    first_time = datetime(2026, 8, 20, 5, 0, tzinfo=UTC)
    second_time = first_time + timedelta(minutes=1)
    scanner = IntradayOpportunityScanner(market, state_path)

    scanner.rank({"RIPPER": _snapshot("RIPPER", 110.0, first_time)}, first_time)
    scanner.rank({"RIPPER": _snapshot("RIPPER", 108.0, second_time)}, second_time)

    payload = json.loads(state_path.read_text(encoding="utf-8"))
    history = payload["opportunity_history"]["RIPPER"]
    assert len(history) == 2
    assert history[0]["price"] == 110.0
    assert history[1]["price"] == 108.0
    assert "score" in history[0]
    assert "intraday_position" in history[0]


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
