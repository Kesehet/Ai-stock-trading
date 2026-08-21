from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
from typing import Protocol
from xml.etree import ElementTree

import httpx

from app.evidence.models import EvidenceItem, EvidenceKind, SourceTier


class EvidenceSource(Protocol):
    def fetch(self) -> list[EvidenceItem]: ...


@dataclass(frozen=True)
class RSSSourceConfig:
    name: str
    url: str
    source_tier: SourceTier
    trust_score: float
    kind: EvidenceKind


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
    return parser.text()


def _child_text(node: ElementTree.Element, *names: str) -> str:
    for child in node:
        local_name = child.tag.rsplit("}", 1)[-1]
        if local_name in names and child.text:
            return child.text.strip()
    return ""


def _parse_published(value: str, fallback: datetime) -> datetime:
    if not value:
        return fallback
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return fallback
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def parse_rss(xml: str, config: RSSSourceConfig, retrieved_at: datetime) -> list[EvidenceItem]:
    root = ElementTree.fromstring(xml)
    items: list[EvidenceItem] = []
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1] not in {"item", "entry"}:
            continue
        title = _child_text(node, "title")
        if not title:
            continue
        link = _child_text(node, "link")
        if not link:
            for child in node:
                if child.tag.rsplit("}", 1)[-1] == "link" and child.attrib.get("href"):
                    link = child.attrib["href"]
                    break
        source_ref = _child_text(node, "guid", "id") or None
        body = _strip_html(_child_text(node, "description", "summary", "content"))
        published_raw = _child_text(node, "pubDate", "published", "updated")
        published_at = _parse_published(published_raw, retrieved_at)
        fingerprint = EvidenceItem.make_fingerprint(
            config.name,
            source_ref,
            link or config.url,
            title,
            published_at,
        )
        items.append(
            EvidenceItem(
                source_name=config.name,
                source_tier=config.source_tier,
                kind=config.kind,
                source_url=link or config.url,
                source_ref=source_ref,
                title=title,
                body=body,
                published_at=published_at,
                retrieved_at=retrieved_at,
                available_at=max(published_at, retrieved_at),
                trust_score=config.trust_score,
                fingerprint=fingerprint,
            )
        )
    return items


class RSSSource:
    def __init__(self, config: RSSSourceConfig, timeout_seconds: float = 20.0) -> None:
        self.config = config
        self.timeout_seconds = timeout_seconds

    def fetch(self) -> list[EvidenceItem]:
        retrieved_at = datetime.now(UTC)
        with httpx.Client(timeout=self.timeout_seconds, follow_redirects=True) as client:
            response = client.get(
                self.config.url,
                headers={"User-Agent": "ai-stock-trading/0.1 research-ingestor"},
            )
            response.raise_for_status()
        return parse_rss(response.text, self.config, retrieved_at)
