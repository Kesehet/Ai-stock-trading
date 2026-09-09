from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.microstructure import BookLevel, BookTick
from app.microstructure_store import KiteFullTickAdapter, MicrostructureEventStore


def test_kite_full_tick_adapter_reads_top_five_depth() -> None:
    adapter = KiteFullTickAdapter({12345: "ABC"})
    raw: dict[str, object] = {
        "instrument_token": 12345,
        "last_price": 50.05,
        "last_quantity": 25,
        "volume": 12_345,
        "exchange_timestamp": datetime(2026, 9, 7, 4, 0, tzinfo=UTC),
        "depth": {
            "buy": [
                {"price": 50.00 - index * 0.05, "quantity": 1000 - index * 50, "orders": 3}
                for index in range(5)
            ],
            "sell": [
                {"price": 50.05 + index * 0.05, "quantity": 200 + index * 20, "orders": 2}
                for index in range(5)
            ],
        },
    }

    tick = adapter.from_tick(raw)

    assert tick is not None
    assert tick.symbol == "ABC"
    assert len(tick.bids) == 5
    assert len(tick.asks) == 5
    assert tick.bids[0].price == 50.0
    assert tick.asks[0].price == 50.05


def test_store_round_trip_preserves_book(tmp_path: Path) -> None:
    path = tmp_path / "microstructure.sqlite3"
    original = _tick(0)
    with MicrostructureEventStore(path) as store:
        event_id = store.record(original)
        restored = list(store.iter_ticks(symbol="ABC"))

    assert event_id > 0
    assert restored == [original]


def test_store_retention_is_bounded_per_symbol(tmp_path: Path) -> None:
    path = tmp_path / "bounded.sqlite3"
    with MicrostructureEventStore(
        path,
        max_events_per_symbol=100,
        prune_every=1,
    ) as store:
        for index in range(105):
            store.record(_tick(index))
        ticks = list(store.iter_ticks(symbol="ABC"))
        count = store.count(symbol="ABC")

    assert count == 100
    assert len(ticks) == 100
    assert ticks[0].volume == 10_005
    assert ticks[-1].volume == 10_104


def _tick(index: int) -> BookTick:
    bid = 49.95 + index * 0.05
    ask = bid + 0.05
    return BookTick(
        symbol="ABC",
        timestamp=datetime(2026, 9, 7, 4, 0, tzinfo=UTC) + timedelta(milliseconds=index),
        last_price=bid,
        last_quantity=10,
        volume=10_000 + index,
        bids=tuple(BookLevel(bid - level * 0.05, 1000 - level * 50, 3) for level in range(5)),
        asks=tuple(BookLevel(ask + level * 0.05, 200 + level * 20, 2) for level in range(5)),
    )
