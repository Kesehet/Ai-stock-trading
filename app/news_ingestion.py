from __future__ import annotations

from urllib.parse import quote_plus

from app.evidence.models import EvidenceKind, SourceTier
from app.evidence.sources import RSSSource, RSSSourceConfig
from app.evidence.store import EvidenceStore


class CompanyNewsIngestor:
    """Fetches a current India-focused news RSS search for one NSE symbol."""

    def __init__(self, store: EvidenceStore) -> None:
        self.store = store

    def ingest(self, symbol: str) -> tuple[int, int]:
        normalized = symbol.strip().upper()
        if not normalized:
            return 0, 0
        query = quote_plus(f'"{normalized}" NSE stock India')
        source = RSSSource(
            RSSSourceConfig(
                name="Google News India",
                url=(
                    "https://news.google.com/rss/search"
                    f"?q={query}&hl=en-IN&gl=IN&ceid=IN:en"
                ),
                source_tier=SourceTier.NEWS,
                trust_score=0.65,
                kind=EvidenceKind.NEWS,
            )
        )
        items = source.fetch()
        inserted = 0
        for item in items[:30]:
            tagged = item.model_copy(update={"symbol": normalized})
            if self.store.put(tagged):
                inserted += 1
        return len(items), inserted
