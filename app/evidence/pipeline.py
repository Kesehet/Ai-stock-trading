from __future__ import annotations

from dataclasses import dataclass

from app.evidence.classifier import classify_event
from app.evidence.models import MarketEvent
from app.evidence.sources import EvidenceSource
from app.evidence.store import EvidenceStore
from app.instruments import InstrumentMaster


@dataclass(frozen=True)
class IngestionResult:
    fetched: int
    inserted: int
    resolved: int
    unresolved: int
    events: tuple[MarketEvent, ...]


class EvidencePipeline:
    def __init__(
        self,
        store: EvidenceStore,
        instrument_master: InstrumentMaster | None = None,
    ) -> None:
        self.store = store
        self.instrument_master = instrument_master

    def ingest(self, source: EvidenceSource) -> IngestionResult:
        items = source.fetch()
        events: list[MarketEvent] = []
        inserted = 0
        resolved = 0
        unresolved = 0
        for raw_item in items:
            item = raw_item
            if item.symbol is None and self.instrument_master is not None:
                instrument = self.instrument_master.resolve_text(f"{item.title} {item.body}")
                if instrument is not None:
                    item = item.model_copy(update={"symbol": instrument.symbol})
                    resolved += 1
                else:
                    unresolved += 1
            elif item.symbol is not None:
                resolved += 1

            if self.store.put(item):
                inserted += 1
                events.append(classify_event(item))
        return IngestionResult(
            fetched=len(items),
            inserted=inserted,
            resolved=resolved,
            unresolved=unresolved,
            events=tuple(events),
        )
