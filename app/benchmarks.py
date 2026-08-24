from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import UTC, datetime
from io import StringIO
from math import sqrt
from statistics import mean, pstdev


@dataclass(frozen=True)
class IndexPoint:
    index_name: str
    timestamp: datetime
    close: float

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None:
            raise ValueError("index timestamp must be timezone-aware")
        if self.close <= 0:
            raise ValueError("index close must be positive")


@dataclass(frozen=True)
class BenchmarkMetrics:
    portfolio_return: float
    benchmark_return: float
    excess_return: float
    tracking_error: float | None
    information_ratio: float | None


class BenchmarkSeries:
    def __init__(self, points: list[IndexPoint] | None = None) -> None:
        self._points: dict[str, list[IndexPoint]] = {}
        for point in points or []:
            self.add(point)

    def add(self, point: IndexPoint) -> None:
        values = self._points.setdefault(point.index_name.upper(), [])
        values.append(point)
        values.sort(key=lambda item: item.timestamp)

    def as_of(self, index_name: str, cutoff: datetime) -> IndexPoint | None:
        visible = [
            point
            for point in self._points.get(index_name.upper(), [])
            if point.timestamp <= cutoff
        ]
        return visible[-1] if visible else None

    def between(self, index_name: str, start: datetime, end: datetime) -> list[IndexPoint]:
        return [
            point
            for point in self._points.get(index_name.upper(), [])
            if start <= point.timestamp <= end
        ]


def _parse_date(value: str) -> datetime:
    raw = value.strip()
    for fmt in ("%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    raise ValueError(f"unsupported NSE index date: {value}")


def _clean_number(value: str) -> float:
    return float(value.strip().replace(",", ""))


def parse_nse_historical_index_csv(
    content: str,
    index_name: str = "NIFTY 50",
) -> BenchmarkSeries:
    """Parse CSV exported from NSE Historical Index Data.

    NSE exports have used slightly different header spellings over time, so the parser
    normalizes headers and accepts the common Date/Close variants.
    """

    reader = csv.DictReader(StringIO(content.lstrip("\ufeff")))
    points: list[IndexPoint] = []
    for row in reader:
        normalized = {
            str(key).strip().upper().replace(" ", "_"): (value or "")
            for key, value in row.items()
            if key is not None
        }
        date_value = normalized.get("DATE") or normalized.get("INDEX_DATE") or ""
        close_value = (
            normalized.get("CLOSE")
            or normalized.get("CLOSING_INDEX_VALUE")
            or normalized.get("CLOSE_INDEX_VALUE")
            or ""
        )
        if not date_value or not close_value:
            continue
        points.append(
            IndexPoint(
                index_name=index_name,
                timestamp=_parse_date(date_value),
                close=_clean_number(close_value),
            )
        )
    return BenchmarkSeries(points)


def _period_returns(values: list[float]) -> list[float]:
    return [
        (values[index] / values[index - 1]) - 1
        for index in range(1, len(values))
        if values[index - 1] > 0
    ]


def compare_to_benchmark(
    portfolio_values: list[float],
    benchmark_values: list[float],
    periods_per_year: int = 252,
) -> BenchmarkMetrics:
    count = min(len(portfolio_values), len(benchmark_values))
    if count < 2:
        raise ValueError("at least two aligned portfolio and benchmark values are required")
    portfolio = portfolio_values[-count:]
    benchmark = benchmark_values[-count:]
    portfolio_return = (portfolio[-1] / portfolio[0]) - 1
    benchmark_return = (benchmark[-1] / benchmark[0]) - 1
    portfolio_period = _period_returns(portfolio)
    benchmark_period = _period_returns(benchmark)
    active = [
        portfolio_value - benchmark_value
        for portfolio_value, benchmark_value in zip(
            portfolio_period,
            benchmark_period,
            strict=True,
        )
    ]
    tracking_error = None
    information_ratio = None
    if len(active) >= 2:
        daily_tracking = pstdev(active)
        tracking_error = daily_tracking * sqrt(periods_per_year)
        if daily_tracking > 0:
            information_ratio = (mean(active) / daily_tracking) * sqrt(periods_per_year)
    return BenchmarkMetrics(
        portfolio_return=portfolio_return,
        benchmark_return=benchmark_return,
        excess_return=portfolio_return - benchmark_return,
        tracking_error=tracking_error,
        information_ratio=information_ratio,
    )
