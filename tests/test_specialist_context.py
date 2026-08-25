from datetime import UTC, datetime, timedelta

import pytest

from app.brokers import PaperBroker
from app.evidence.store import EvidenceStore
from app.fundamentals import FundamentalSnapshot, FundamentalStore
from app.macro_context import MacroSnapshot, MacroStore
from app.market_data import Candle, HistoricalDataStore
from app.research_team import ResearchContextBuilder, ResearchRole
from app.technical_features import calculate_technical_features


def _candles(symbol: str, start: datetime, count: int = 60) -> list[Candle]:
    return [
        Candle(
            symbol=symbol,
            timestamp=start + timedelta(days=index),
            open=100 + index,
            high=101 + index,
            low=99 + index,
            close=100 + index,
            volume=1_000_000 + (index * 10_000),
        )
        for index in range(count)
    ]


def test_technical_features_are_deterministic() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    features = calculate_technical_features(_candles("TCS", start))

    assert features.sma_20 is not None
    assert features.sma_50 is not None
    assert features.ema_12 is not None
    assert features.ema_26 is not None
    assert features.rsi_14 == 100.0
    assert features.return_20d is not None


def test_fundamental_store_blocks_future_snapshot() -> None:
    cutoff = datetime(2026, 8, 1, tzinfo=UTC)
    store = FundamentalStore(
        [
            FundamentalSnapshot(
                symbol="TCS",
                available_at=cutoff,
                revenue=120,
                prior_revenue=100,
                net_income=24,
                prior_net_income=20,
                equity=80,
                debt=8,
                market_cap=480,
            ),
            FundamentalSnapshot(
                symbol="TCS",
                available_at=cutoff + timedelta(days=1),
                revenue=999,
            ),
        ]
    )

    visible = store.latest_as_of("TCS", cutoff)

    assert visible is not None
    assert visible.revenue == 120
    assert visible.ratios()["revenue_growth"] == pytest.approx(0.2)


def test_context_builder_gives_each_role_specific_context(tmp_path) -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    as_of = start + timedelta(days=59)
    market = HistoricalDataStore(_candles("TCS", start))
    fundamentals = FundamentalStore(
        [
            FundamentalSnapshot(
                symbol="TCS",
                available_at=as_of,
                revenue=120,
                prior_revenue=100,
                net_income=24,
                prior_net_income=20,
                equity=80,
                debt=8,
            )
        ]
    )
    macro = MacroStore(
        [MacroSnapshot(available_at=as_of, repo_rate=0.055, cpi_yoy=0.04, india_vix=14)]
    )
    builder = ResearchContextBuilder(
        market,
        EvidenceStore(tmp_path / "evidence.db"),
        fundamentals=fundamentals,
        macro=macro,
        portfolio=PaperBroker(starting_cash=100_000),
    )

    snapshot = builder.build("TCS", as_of)

    technical = snapshot.context_for(ResearchRole.TECHNICAL)
    fundamental = snapshot.context_for(ResearchRole.FUNDAMENTAL)
    news = snapshot.context_for(ResearchRole.NEWS)
    portfolio = snapshot.context_for(ResearchRole.PORTFOLIO)
    assert "rsi_14=" in technical
    assert "revenue_growth=0.2000" in fundamental
    assert "repo_rate=0.0550" in news
    assert "cash_weight=1.0000" in portfolio
    assert "revenue_growth" not in technical
