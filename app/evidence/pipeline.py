from __future__ import annotations

from dataclasses import dataclass

from app.evidence.classifier import classify_event
from app.evidence.models import MarketEvent
from app.evidence.sources import EvidenceSource
from app.evidence.store import EvidenceStore


@dataclass(frozen=True)
class IngestionResult:
    fetched: int
    inserted: int
    events: tuple[MarketEvent, ...]


class EvidencePipeline:
    def __init__(self, store: EvidenceStore) -> None:
        self.store = store

    def ingest(self, source: EvidenceSource) -> IngestionResult:
        items = source.fetch()
        events: list[MarketEvent] = []
        inserted = 0
        for item in items:
            if self.store.put(item):
                inserted += 1
                events.append(classify_event(item))
        return IngestionResult(
            fetched=len(items),
            inserted=inserted,
            events=tuple(events),
        )
