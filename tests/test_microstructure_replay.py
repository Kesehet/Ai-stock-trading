from datetime import UTC, datetime, timedelta

from app.microstructure import BookLevel, BookTick
from app.microstructure_replay import MicrostructureReplay, ReplayConfig, make_event_labels


def test_event_labels_measure_future_path_without_mutating_ticks() -> None:
    series = _rising_series(12)
    labels = make_event_labels(series, horizons=(1, 3, 5))

    first = next(label for label in labels if label.event_index == 0 and label.horizon_events == 3)
    assert first.direction == 1
    assert first.move_ticks > 0
    assert first.mfe_ticks >= first.move_ticks
    assert first.mae_ticks > 0


def test_replay_waits_for_latency_event_and_scores_net_rupees() -> None:
    series = _rising_series(90)
    replay = MicrostructureReplay(
        ReplayConfig(
            horizons=(1, 3, 5, 10),
            latency_events=1,
            target_ticks=12,
            stop_ticks=2,
            min_probability=0.60,
            min_expected_net_rupees=0.01,
            training_fraction=0.50,
            min_training_samples=20,
        )
    )

    report = replay.run(series)

    assert report.scores
    assert report.fitted_models > 0
    assert report.trades
    assert all(trade.entry_timestamp > trade.signal_timestamp for trade in report.trades)
    assert any(score.ending_nav > 500.0 for score in report.scores)
    assert any(score.costs > 0 for score in report.scores if score.trades)


def test_replay_keeps_whole_share_500_rupee_position_cap() -> None:
    series = _rising_series(50, start_price=249.95)
    replay = MicrostructureReplay(
        ReplayConfig(
            horizons=(5,),
            latency_events=1,
            target_ticks=12,
            stop_ticks=2,
            min_probability=0.55,
            min_expected_net_rupees=-10.0,
            training_fraction=0.40,
            min_training_samples=10,
        )
    )

    report = replay.run(series)

    assert report.trades
    assert all(trade.quantity == 1 for trade in report.trades)


def _rising_series(count: int, *, start_price: float = 49.95) -> list[BookTick]:
    base = datetime(2026, 9, 7, 4, 0, tzinfo=UTC)
    series: list[BookTick] = []
    for index in range(count):
        bid = start_price + index * 0.05
        ask = bid + 0.05
        series.append(
            BookTick(
                symbol="TREND",
                timestamp=base + timedelta(milliseconds=100 * index),
                last_price=bid,
                last_quantity=50,
                volume=10_000 + index * 100,
                bids=tuple(
                    BookLevel(bid - level * 0.05, 2000 - level * 100, 5)
                    for level in range(5)
                ),
                asks=tuple(
                    BookLevel(ask + level * 0.05, 200 + level * 20, 2)
                    for level in range(5)
                ),
            )
        )
    return series
