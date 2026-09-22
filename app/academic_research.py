from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from hashlib import sha256
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, cast, Protocol
from uuid import uuid4

import httpx
from pydantic import BaseModel, Field, model_validator


DEFAULT_ACADEMIC_TOPICS: tuple[str, ...] = (
    "Indian equities momentum market regime",
    "NSE intraday momentum transaction costs",
    "equity order book imbalance market microstructure",
    "volatility adjusted position sizing momentum",
    "breakout pullback entry momentum",
)


class AcademicHypothesisStatus(StrEnum):
    DISCOVERED = "discovered"
    EXTRACTED = "extracted"
    REPLICATING = "replicating"
    SHADOW = "shadow"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    WATCH = "watch"


class AcademicPaper(BaseModel):
    id: str
    source: str = Field(min_length=1, max_length=64)
    doi: str | None = None
    title: str = Field(min_length=1)
    abstract: str = ""
    authors: tuple[str, ...] = ()
    source_url: str = Field(min_length=1)
    published_at: datetime
    discovered_at: datetime
    topics: tuple[str, ...] = ()
    fingerprint: str

    @model_validator(mode="after")
    def validate_times(self) -> AcademicPaper:
        if self.published_at.tzinfo is None or self.discovered_at.tzinfo is None:
            raise ValueError("academic paper timestamps must be timezone-aware")
        return self

    @staticmethod
    def make_fingerprint(doi: str | None, title: str, source_url: str) -> str:
        stable = (doi or source_url).strip().lower()
        return sha256(f"{stable}|{title.strip().lower()}".encode()).hexdigest()


class AcademicHypothesis(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    paper_id: str
    topic: str
    statement: str = Field(min_length=1)
    status: AcademicHypothesisStatus = AcademicHypothesisStatus.DISCOVERED
    applicable_market: str = "NSE cash equities"
    applicable_horizon: str = ""
    proposed_feature: str = ""
    claimed_effect: str = ""
    transaction_cost_assumption: str = ""
    out_of_sample: bool | None = None
    lookahead_risk: str = ""
    notes: str = ""
    created_at: datetime
    updated_at: datetime
    accepted_at: datetime | None = None

    @model_validator(mode="after")
    def validate_times(self) -> AcademicHypothesis:
        for value in (self.created_at, self.updated_at, self.accepted_at):
            if value is not None and value.tzinfo is None:
                raise ValueError("academic hypothesis timestamps must be timezone-aware")
        if self.status == AcademicHypothesisStatus.ACCEPTED and self.accepted_at is None:
            raise ValueError("accepted hypotheses require accepted_at")
        return self

    def as_context(self) -> str:
        return " | ".join(
            [
                f"topic={self.topic}",
                f"statement={self.statement}",
                f"market={self.applicable_market}",
                f"horizon={self.applicable_horizon or 'unspecified'}",
                f"feature={self.proposed_feature or 'unspecified'}",
                f"claimed_effect={self.claimed_effect or 'unspecified'}",
                f"costs={self.transaction_cost_assumption or 'unspecified'}",
                f"oos={self.out_of_sample}",
                f"lookahead_risk={self.lookahead_risk or 'unspecified'}",
                "status=accepted",
            ]
        )


@dataclass(frozen=True)
class AcademicRefreshResult:
    topics: int
    fetched: int
    inserted: int


class AcademicPaperSource(Protocol):
    def search(self, topic: str, discovered_at: datetime) -> list[AcademicPaper]: ...


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def text(self) -> str:
        return " ".join(part.strip() for part in self.parts if part.strip())


def _strip_html(value: str) -> str:
    parser = _TextExtractor()
    parser.feed(unescape(value))
    return re.sub(r"\s+", " ", parser.text()).strip()


def _crossref_datetime(item: dict[str, Any], fallback: datetime) -> datetime:
    for key in ("published-online", "published-print", "published", "issued"):
        raw = item.get(key)
        if not isinstance(raw, dict):
            continue
        date_parts = raw.get("date-parts")
        if not isinstance(date_parts, list) or not date_parts or not date_parts[0]:
            continue
        parts = list(date_parts[0])
        try:
            year = int(parts[0])
            month = int(parts[1]) if len(parts) > 1 else 1
            day = int(parts[2]) if len(parts) > 2 else 1
            return datetime(year, month, day, tzinfo=UTC)
        except (TypeError, ValueError):
            continue

    created = item.get("created")
    if isinstance(created, dict):
        raw = created.get("date-time")
        if isinstance(raw, str):
            try:
                parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                if parsed.tzinfo is not None:
                    return parsed.astimezone(UTC)
            except ValueError:
                pass
    return fallback


def parse_crossref_ssrn_items(
    payload: dict[str, Any],
    topic: str,
    discovered_at: datetime,
) -> list[AcademicPaper]:
    if discovered_at.tzinfo is None:
        raise ValueError("discovered_at must be timezone-aware")
    message = payload.get("message")
    if not isinstance(message, dict):
        return []
    raw_items = message.get("items")
    if not isinstance(raw_items, list):
        return []

    papers: list[AcademicPaper] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        doi_raw = raw.get("DOI")
        doi = str(doi_raw).strip().lower() if doi_raw else None
        if doi is not None and not doi.startswith("10.2139/ssrn."):
            continue

        titles = raw.get("title")
        if not isinstance(titles, list) or not titles:
            continue
        title = _strip_html(str(titles[0]))
        if not title:
            continue

        abstract_id = doi.rsplit(".", 1)[-1] if doi else ""
        if abstract_id.isdigit():
            source_url = (
                "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=" + abstract_id
            )
        else:
            source_url = str(raw.get("URL") or "").strip()
        if not source_url:
            continue

        authors: list[str] = []
        raw_authors = raw.get("author")
        if isinstance(raw_authors, list):
            for author in raw_authors:
                if not isinstance(author, dict):
                    continue
                name = " ".join(
                    part
                    for part in (
                        str(author.get("given") or "").strip(),
                        str(author.get("family") or "").strip(),
                    )
                    if part
                )
                if name:
                    authors.append(name)

        abstract = _strip_html(str(raw.get("abstract") or ""))
        published_at = _crossref_datetime(raw, discovered_at)
        fingerprint = AcademicPaper.make_fingerprint(doi, title, source_url)
        papers.append(
            AcademicPaper(
                id=fingerprint,
                source="SSRN via Crossref",
                doi=doi,
                title=title,
                abstract=abstract,
                authors=tuple(authors),
                source_url=source_url,
                published_at=published_at,
                discovered_at=discovered_at,
                topics=(topic,),
                fingerprint=fingerprint,
            )
        )
    return papers


class CrossrefSSRNSource:
    """Discover SSRN metadata through Crossref instead of scraping SSRN pages."""

    endpoint = "https://api.crossref.org/prefixes/10.2139/works"

    def __init__(
        self,
        *,
        rows_per_topic: int = 8,
        lookback_days: int = 3650,
        timeout_seconds: float = 20.0,
        mailto: str = "",
    ) -> None:
        self.rows_per_topic = max(1, min(rows_per_topic, 50))
        self.lookback_days = max(30, lookback_days)
        self.timeout_seconds = timeout_seconds
        self.mailto = mailto.strip()

    def search(self, topic: str, discovered_at: datetime) -> list[AcademicPaper]:
        if discovered_at.tzinfo is None:
            raise ValueError("discovered_at must be timezone-aware")
        from_date = (discovered_at - timedelta(days=self.lookback_days)).date().isoformat()
        params = {
            "query.bibliographic": topic,
            "filter": f"from-pub-date:{from_date}",
            "rows": str(self.rows_per_topic),
            "sort": "published",
            "order": "desc",
        }
        if self.mailto:
            params["mailto"] = self.mailto
        headers = {"User-Agent": "ai-stock-trading/0.1 academic-research"}
        with httpx.Client(timeout=self.timeout_seconds, follow_redirects=True) as client:
            response = client.get(self.endpoint, params=params, headers=headers)
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict):
            return []
        return parse_crossref_ssrn_items(payload, topic, discovered_at)


class AcademicResearchStore:
    """Durable paper + hypothesis memory. Only ACCEPTED hypotheses reach trading context."""

    def __init__(self, path: str | Path = "academic-research.sqlite3") -> None:
        self.path = str(path)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS academic_papers (
                    id TEXT PRIMARY KEY,
                    doi TEXT,
                    discovered_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_academic_papers_doi "
                "ON academic_papers(doi) WHERE doi IS NOT NULL"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS academic_hypotheses (
                    id TEXT PRIMARY KEY,
                    paper_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    accepted_at TEXT,
                    payload TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_academic_hypothesis_status "
                "ON academic_hypotheses(status, accepted_at)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS academic_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )

    def put_paper(self, paper: AcademicPaper) -> bool:
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO academic_papers(id, doi, discovered_at, payload)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        paper.id,
                        paper.doi,
                        paper.discovered_at.isoformat(),
                        paper.model_dump_json(),
                    ),
                )
        except sqlite3.IntegrityError:
            return False
        return True

    def upsert_hypothesis(self, hypothesis: AcademicHypothesis) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO academic_hypotheses(
                    id, paper_id, status, updated_at, accepted_at, payload
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    paper_id=excluded.paper_id,
                    status=excluded.status,
                    updated_at=excluded.updated_at,
                    accepted_at=excluded.accepted_at,
                    payload=excluded.payload
                """,
                (
                    hypothesis.id,
                    hypothesis.paper_id,
                    hypothesis.status.value,
                    hypothesis.updated_at.isoformat(),
                    (
                        hypothesis.accepted_at.isoformat()
                        if hypothesis.accepted_at is not None
                        else None
                    ),
                    hypothesis.model_dump_json(),
                ),
            )

    def list_recent_papers(self, limit: int = 50) -> list[AcademicPaper]:
        if limit <= 0:
            return []
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload FROM academic_papers
                ORDER BY discovered_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            AcademicPaper.model_validate_json(cast(str, row["payload"]))
            for row in rows
        ]

    def list_accepted_as_of(
        self,
        cutoff: datetime,
        limit: int = 8,
    ) -> list[AcademicHypothesis]:
        if cutoff.tzinfo is None:
            raise ValueError("cutoff must be timezone-aware")
        if limit <= 0:
            return []
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload FROM academic_hypotheses
                WHERE status = ?
                  AND accepted_at IS NOT NULL
                  AND accepted_at <= ?
                ORDER BY accepted_at DESC
                LIMIT ?
                """,
                (
                    AcademicHypothesisStatus.ACCEPTED.value,
                    cutoff.isoformat(),
                    limit,
                ),
            ).fetchall()
        return [
            AcademicHypothesis.model_validate_json(cast(str, row["payload"]))
            for row in rows
        ]

    def _set_meta(self, key: str, value: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO academic_meta(key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (key, value),
            )

    def _get_meta(self, key: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM academic_meta WHERE key = ?",
                (key,),
            ).fetchone()
        if row is None:
            return None
        return cast(str, row["value"])

    def mark_refresh_attempt(self, value: datetime) -> None:
        self._set_meta("last_refresh_attempt_at", value.isoformat())

    def mark_refresh_success(self, value: datetime) -> None:
        self._set_meta("last_refresh_success_at", value.isoformat())

    def last_refresh_attempt(self) -> datetime | None:
        raw = self._get_meta("last_refresh_attempt_at")
        if not raw:
            return None
        try:
            value = datetime.fromisoformat(raw)
        except ValueError:
            return None
        return value if value.tzinfo is not None else None


class AcademicResearchService:
    def __init__(
        self,
        store: AcademicResearchStore,
        source: AcademicPaperSource,
        topics: tuple[str, ...] = DEFAULT_ACADEMIC_TOPICS,
    ) -> None:
        self.store = store
        self.source = source
        self.topics = tuple(topic.strip() for topic in topics if topic.strip())

    def due(self, now: datetime, refresh_hours: float = 24.0) -> bool:
        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        previous = self.store.last_refresh_attempt()
        if previous is None:
            return True
        return (now - previous).total_seconds() >= refresh_hours * 3600.0

    def refresh(self, now: datetime) -> AcademicRefreshResult:
        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        self.store.mark_refresh_attempt(now)
        fetched = 0
        inserted = 0
        for topic in self.topics:
            papers = self.source.search(topic, now)
            fetched += len(papers)
            inserted += sum(1 for paper in papers if self.store.put_paper(paper))
        self.store.mark_refresh_success(now)
        return AcademicRefreshResult(
            topics=len(self.topics),
            fetched=fetched,
            inserted=inserted,
        )
