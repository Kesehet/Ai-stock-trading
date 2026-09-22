from datetime import UTC, datetime, timedelta

from app.academic_research import (
    AcademicHypothesis,
    AcademicHypothesisStatus,
    AcademicPaper,
    AcademicResearchService,
    AcademicResearchStore,
    parse_crossref_ssrn_items,
)
from app.evidence.store import EvidenceStore
from app.market_data import HistoricalDataStore
from app.research_team import ResearchContextBuilder, ResearchRole


def _paper(now: datetime) -> AcademicPaper:
    return AcademicPaper(
        id="paper-1",
        source="SSRN via Crossref",
        doi="10.2139/ssrn.1234567",
        title="Momentum and Market Regimes in Indian Equities",
        abstract="Momentum varies across market regimes.",
        authors=("A Researcher",),
        source_url="https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1234567",
        published_at=now - timedelta(days=30),
        discovered_at=now,
        topics=("Indian equities momentum market regime",),
        fingerprint="paper-1",
    )


def test_crossref_ssrn_parser_normalizes_metadata() -> None:
    now = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)
    payload = {
        "message": {
            "items": [
                {
                    "DOI": "10.2139/ssrn.1234567",
                    "title": ["<b>Momentum</b> and Regimes"],
                    "abstract": ["ignored"],
                    "author": [{"given": "Ada", "family": "Quant"}],
                    "published": {"date-parts": [[2026, 9, 1]]},
                },
                {
                    "DOI": "10.1000/not-ssrn",
                    "title": ["Other paper"],
                    "URL": "https://example.test/other",
                },
            ]
        }
    }

    papers = parse_crossref_ssrn_items(payload, "Indian equities momentum", now)

    assert len(papers) == 1
    assert papers[0].doi == "10.2139/ssrn.1234567"
    assert papers[0].title == "Momentum and Regimes"
    assert papers[0].authors == ("Ada Quant",)
    assert papers[0].source_url.endswith("abstract_id=1234567")
    assert papers[0].published_at == datetime(2026, 9, 1, tzinfo=UTC)


def test_store_deduplicates_papers_and_gates_hypotheses(tmp_path) -> None:
    now = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)
    store = AcademicResearchStore(tmp_path / "academic.sqlite3")
    paper = _paper(now)

    assert store.put_paper(paper) is True
    assert store.put_paper(paper) is False

    watch = AcademicHypothesis(
        id="hypothesis-1",
        paper_id=paper.id,
        topic="regime-aware momentum",
        statement="Test whether momentum weakens in stressed Indian-equity regimes.",
        status=AcademicHypothesisStatus.WATCH,
        proposed_feature="regime_momentum_multiplier",
        created_at=now,
        updated_at=now,
    )
    store.upsert_hypothesis(watch)
    assert store.list_accepted_as_of(now + timedelta(days=1)) == []

    accepted_at = now + timedelta(hours=1)
    store.upsert_hypothesis(
        watch.model_copy(
            update={
                "status": AcademicHypothesisStatus.ACCEPTED,
                "accepted_at": accepted_at,
                "updated_at": accepted_at,
            }
        )
    )
    assert store.list_accepted_as_of(now) == []
    accepted = store.list_accepted_as_of(now + timedelta(hours=2))
    assert len(accepted) == 1
    assert accepted[0].proposed_feature == "regime_momentum_multiplier"


def test_only_accepted_academic_research_enters_trading_context(tmp_path) -> None:
    now = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)
    academic = AcademicResearchStore(tmp_path / "academic.sqlite3")
    paper = _paper(now)
    academic.put_paper(paper)
    hypothesis = AcademicHypothesis(
        id="accepted-1",
        paper_id=paper.id,
        topic="regime-aware momentum",
        statement="Use regime as a prior when evaluating momentum.",
        status=AcademicHypothesisStatus.ACCEPTED,
        proposed_feature="regime_momentum_multiplier",
        created_at=now - timedelta(days=1),
        updated_at=now - timedelta(hours=1),
        accepted_at=now - timedelta(hours=1),
    )
    academic.upsert_hypothesis(hypothesis)

    builder = ResearchContextBuilder(
        HistoricalDataStore(),
        EvidenceStore(tmp_path / "evidence.sqlite3"),
        academic=academic,
    )
    snapshot = builder.build("TCS", now)

    assert "regime-aware momentum" in snapshot.academic_text
    context = snapshot.context_for(ResearchRole.PORTFOLIO)
    assert "VALIDATED ACADEMIC CONTEXT" in context
    assert "regime_momentum_multiplier" in context


class FakeSource:
    def __init__(self, paper: AcademicPaper) -> None:
        self.paper = paper
        self.calls: list[str] = []

    def search(self, topic: str, discovered_at: datetime) -> list[AcademicPaper]:
        self.calls.append(topic)
        return [self.paper.model_copy(update={"discovered_at": discovered_at})]


def test_daily_refresh_is_deduplicated_and_rate_limited(tmp_path) -> None:
    now = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)
    store = AcademicResearchStore(tmp_path / "academic.sqlite3")
    source = FakeSource(_paper(now))
    service = AcademicResearchService(store, source, topics=("momentum", "microstructure"))

    assert service.due(now, refresh_hours=24)
    first = service.refresh(now)
    assert first.fetched == 2
    assert first.inserted == 1
    assert service.due(now + timedelta(hours=23), refresh_hours=24) is False
    assert service.due(now + timedelta(hours=25), refresh_hours=24) is True
