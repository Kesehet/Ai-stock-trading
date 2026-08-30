from datetime import UTC, datetime, timedelta

from app.evidence.models import EvidenceItem, EvidenceKind, SourceTier
from app.evidence.store import EvidenceStore
from app.market_data import Candle, HistoricalDataStore
from app.materiality import score_evidence
from app.models import Side
from app.nse_sources import parse_nse_equity_csv
from app.research_team import (
    FundDecision,
    ResearchContextBuilder,
    ResearchReport,
    ResearchRole,
    ResearchTeam,
)


class FakeLLM:
    def generate_structured(self, prompt: str, response_model):
        if response_model is ResearchReport:
            role = next(
                (
                    candidate
                    for candidate in ResearchRole
                    if f"{candidate.value} analyst" in prompt
                    or f"{candidate.value} research role" in prompt
                ),
                ResearchRole.MANAGER,
            )
            return ResearchReport(
                role=role,
                score=0.4,
                confidence=0.7,
                summary="Constructive evidence",
                key_points=("trend positive",),
                evidence_ids=(),
            )
        if response_model is FundDecision:
            return FundDecision(
                action=Side.BUY,
                target_allocation_pct=0.10,
                confidence=0.7,
                horizon="2-8 weeks",
                thesis="Multiple agents are constructive",
            )
        raise AssertionError("unexpected response model")


class HallucinatingEvidenceLLM(FakeLLM):
    def __init__(self, valid_id: str) -> None:
        self.valid_id = valid_id

    def generate_structured(self, prompt: str, response_model):
        if response_model is ResearchReport:
            report = super().generate_structured(prompt, response_model)
            return report.model_copy(
                update={"evidence_ids": (self.valid_id, "made-up-evidence-id")}
            )
        if response_model is FundDecision:
            decision = super().generate_structured(prompt, response_model)
            return decision.model_copy(
                update={"evidence_ids": ("made-up-evidence-id", self.valid_id)}
            )
        raise AssertionError("unexpected response model")


def test_nse_equity_csv_parser_keeps_eq_series() -> None:
    content = (
        "SYMBOL,NAME OF COMPANY, SERIES,DATE OF LISTING,PAID UP VALUE,MARKET LOT,"
        "ISIN NUMBER,FACE VALUE\n"
        "TCS,Tata Consultancy Services Limited,EQ,25-AUG-2004,1,1,INE467B01029,1\n"
        "ABC,ABC Preference Limited,P1,01-JAN-2020,10,1,INE000000001,10\n"
    )
    master = parse_nse_equity_csv(content)

    assert master.require("TCS").isin == "INE467B01029"
    assert master.resolve("ABC") is None


def test_official_regulatory_evidence_scores_high() -> None:
    now = datetime(2026, 8, 22, 1, 0, tzinfo=UTC)
    item = EvidenceItem(
        source_name="NSE announcements",
        source_tier=SourceTier.OFFICIAL,
        kind=EvidenceKind.ANNOUNCEMENT,
        source_url="https://example.test/filing",
        title="SEBI regulatory action and penalty",
        body="Settlement order disclosed by the company.",
        symbol="TCS",
        published_at=now,
        retrieved_at=now,
        available_at=now,
        trust_score=1.0,
        fingerprint="abc",
    )

    score = score_evidence(item)

    assert score.value >= 0.85


def test_context_builder_blocks_future_market_data_and_evidence(tmp_path) -> None:
    cutoff = datetime(2026, 8, 22, 1, 0, tzinfo=UTC)
    market = HistoricalDataStore(
        [
            Candle("TCS", cutoff, 100, 101, 99, 100, 1000),
            Candle("TCS", cutoff.replace(hour=2), 110, 111, 109, 110, 1000),
        ]
    )
    store = EvidenceStore(tmp_path / "evidence.db")
    visible = EvidenceItem(
        source_name="NSE",
        source_tier=SourceTier.OFFICIAL,
        kind=EvidenceKind.ANNOUNCEMENT,
        source_url="https://example.test/visible",
        title="Board meeting",
        symbol="TCS",
        published_at=cutoff,
        retrieved_at=cutoff,
        available_at=cutoff,
        trust_score=1.0,
        fingerprint="visible",
    )
    future_at = cutoff.replace(hour=2)
    future = EvidenceItem(
        source_name="NSE",
        source_tier=SourceTier.OFFICIAL,
        kind=EvidenceKind.ANNOUNCEMENT,
        source_url="https://example.test/future",
        title="Future result",
        symbol="TCS",
        published_at=future_at,
        retrieved_at=future_at,
        available_at=future_at,
        trust_score=1.0,
        fingerprint="future",
    )
    store.put(visible)
    store.put(future)

    snapshot = ResearchContextBuilder(market, store).build("TCS", cutoff)

    assert "C=100.00" in snapshot.market_text
    assert "C=110.00" not in snapshot.market_text
    assert "Board meeting" in snapshot.evidence_text
    assert "Future result" not in snapshot.evidence_text


def test_context_prioritizes_material_official_evidence_over_fresh_noise(tmp_path) -> None:
    now = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)
    store = EvidenceStore(tmp_path / "evidence.db")
    important = EvidenceItem(
        source_name="NSE",
        source_tier=SourceTier.OFFICIAL,
        kind=EvidenceKind.ANNOUNCEMENT,
        source_url="https://example.test/regulatory",
        title="SEBI regulatory action and penalty",
        body="Material settlement order.",
        symbol="TCS",
        published_at=now - timedelta(days=2),
        retrieved_at=now - timedelta(days=2),
        available_at=now - timedelta(days=2),
        trust_score=1.0,
        fingerprint="material-official",
    )
    noise = EvidenceItem(
        source_name="Generic news",
        source_tier=SourceTier.NEWS,
        kind=EvidenceKind.NEWS,
        source_url="https://example.test/noise",
        title="TCS shares in focus today",
        body="Routine market chatter.",
        symbol="TCS",
        published_at=now - timedelta(minutes=5),
        retrieved_at=now - timedelta(minutes=5),
        available_at=now - timedelta(minutes=5),
        trust_score=0.6,
        fingerprint="fresh-noise",
    )
    store.put(important)
    store.put(noise)

    snapshot = ResearchContextBuilder(
        HistoricalDataStore(),
        store,
        max_evidence=1,
    ).build("TCS", now)

    assert "SEBI regulatory action and penalty" in snapshot.evidence_text
    assert "TCS shares in focus today" not in snapshot.evidence_text
    assert "materiality=" in snapshot.evidence_text


def test_research_team_rejects_hallucinated_evidence_ids(tmp_path) -> None:
    as_of = datetime(2026, 8, 22, 1, 0, tzinfo=UTC)
    evidence = EvidenceStore(tmp_path / "evidence.db")
    item = EvidenceItem(
        source_name="NSE",
        source_tier=SourceTier.OFFICIAL,
        kind=EvidenceKind.ANNOUNCEMENT,
        source_url="https://example.test/result",
        title="Quarterly financial results",
        symbol="TCS",
        published_at=as_of,
        retrieved_at=as_of,
        available_at=as_of,
        trust_score=1.0,
        fingerprint="valid-result",
    )
    evidence.put(item)
    context = ResearchContextBuilder(HistoricalDataStore(), evidence)
    team = ResearchTeam(HallucinatingEvidenceLLM(item.id), context)  # type: ignore[arg-type]

    reports, decision = team.run("TCS", as_of)

    assert all(report.evidence_ids == (item.id,) for report in reports)
    assert decision.evidence_ids == (item.id,)


def test_research_team_emits_structured_trade_intent(tmp_path) -> None:
    as_of = datetime(2026, 8, 22, 1, 0, tzinfo=UTC)
    market = HistoricalDataStore(
        [Candle("TCS", as_of, 100, 101, 99, 100, 1000)]
    )
    evidence = EvidenceStore(tmp_path / "evidence.db")
    context = ResearchContextBuilder(market, evidence)
    team = ResearchTeam(FakeLLM(), context)  # type: ignore[arg-type]

    intent = team.trade_intent("TCS", as_of)

    assert intent.side == Side.BUY
    assert intent.target_allocation_pct == 0.10
    assert intent.strategy_id == "multi_agent_fund_v3_active"
    assert intent.data_cutoff_at == as_of
