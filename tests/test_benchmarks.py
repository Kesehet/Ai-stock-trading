import pytest

from app.benchmarks import compare_to_benchmark, parse_nse_historical_index_csv


def test_parse_nse_historical_index_csv() -> None:
    content = (
        "Date,Open,High,Low,Close,Shares Traded,Turnover (₹ Cr)\n"
        "01-Jan-2026,26000,26100,25900,26050,1000,200\n"
        "02-Jan-2026,26050,26200,26000,26150,1100,210\n"
    )

    series = parse_nse_historical_index_csv(content)
    points = series.between(
        "NIFTY 50",
        series.as_of("NIFTY 50", __import__("datetime").datetime.max.replace(
            tzinfo=__import__("datetime").UTC
        )).timestamp,
        __import__("datetime").datetime.max.replace(tzinfo=__import__("datetime").UTC),
    )

    assert len(points) == 1
    assert series.as_of(
        "NIFTY 50",
        __import__("datetime").datetime.max.replace(tzinfo=__import__("datetime").UTC),
    ).close == 26150


def test_compare_to_benchmark_calculates_excess_return() -> None:
    metrics = compare_to_benchmark(
        [100_000, 101_000, 103_000, 105_000],
        [100, 100.5, 101.5, 102],
    )

    assert metrics.portfolio_return == pytest.approx(0.05)
    assert metrics.benchmark_return == pytest.approx(0.02)
    assert metrics.excess_return == pytest.approx(0.03)
    assert metrics.tracking_error is not None
