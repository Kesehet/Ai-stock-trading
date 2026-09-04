from datetime import UTC, datetime, timedelta

from app.microstructure import BookLevel, BookTick, MicrostructureConfig, MicrostructureEngine


def tick(
    *,
    bid: float = 49.95,
    ask: float = 50.00,
    bid_qty: int = 900,
    ask_qty: int = 100,
    last: float = 49.95,
    volume: int = 10_000,
    second: int = 0,
) -> BookTick:
    bids = tuple(BookLevel(bid - i * 0.05, max(bid_qty - i * 50, 1), 3) for i in range(5))
    asks = tuple(BookLevel(ask + i * 0.05, max(ask_qty + i * 20, 1), 3) for i in range(5))
    return BookTick(
        symbol="TEST",
        timestamp=datetime(2026, 9, 7, 4, 0, second, tzinfo=UTC),
        last_price=last,
        last_quantity=25,
        volume=volume,
        bids=bids,
        asks=asks,
    )


def test_microprice_moves_toward_ask_when_bid_queue_dominates() -> None:
    engine = MicrostructureEngine()
    features = engine.features(tick(), None)
    assert features.level1_imbalance > 0.7
    assert features.microprice > features.mid
    assert features.microprice_ticks > 0


def test_order_flow_detects_bid_build_and_ask_depletion() -> None:
    engine = MicrostructureEngine()
    first = tick(bid_qty=500, ask_qty=500)
    second = tick(bid_qty=900, ask_qty=200, last=50.0, volume=10_100, second=1)
    features = engine.features(second, first)
    assert features.order_flow_imbalance > 0
    assert features.trade_momentum > 0


def test_expensive_share_is_not_executable_with_half_of_500_capital() -> None:
    engine = MicrostructureEngine(MicrostructureConfig(min_probability=0.50, min_expected_net_rupees=-99))
    expensive = tick(bid=299.95, ask=300.0, last=300.0)
    assert engine.on_tick(expensive) == []


def test_one_tick_profit_is_rejected_after_intraday_friction() -> None:
    config = MicrostructureConfig(
        target_ticks=1,
        stop_ticks=1,
        min_probability=0.50,
        min_expected_net_rupees=0.01,
    )
    engine = MicrostructureEngine(config)
    assert engine.on_tick(tick()) == []


def test_strong_low_price_book_can_emit_shadow_opportunity() -> None:
    config = MicrostructureConfig(
        target_ticks=12,
        stop_ticks=2,
        min_probability=0.60,
        min_expected_net_rupees=0.05,
    )
    engine = MicrostructureEngine(config)
    first = tick(bid_qty=500, ask_qty=500)
    engine.on_tick(first)
    strong = BookTick(
        **{
            **tick(bid_qty=1800, ask_qty=50, last=50.05, volume=10_500, second=1).__dict__,
            "timestamp": first.timestamp + timedelta(seconds=1),
        }
    )
    opportunities = engine.on_tick(strong)
    assert opportunities
    assert all(op.quantity == 5 for op in opportunities)
    assert all(op.expected_net_rupees > 0 for op in opportunities)
