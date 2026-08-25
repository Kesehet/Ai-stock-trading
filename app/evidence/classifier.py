# ruff: noqa: I001
from __future__ import annotations

from app.evidence.models import EvidenceItem, MarketEvent, MarketEventType


_RULES: tuple[tuple[MarketEventType, tuple[str, ...]], ...] = (
    (
        MarketEventType.FINANCIAL_RESULTS,
        ("financial result", "quarterly result", "earnings"),
    ),
    (MarketEventType.BOARD_MEETING, ("board meeting",)),
    (
        MarketEventType.MANAGEMENT_CHANGE,
        ("appointment", "resignation", "director", "kmp"),
    ),
    (MarketEventType.LARGE_ORDER, ("order win", "contract award", "work order")),
    (MarketEventType.ACQUISITION, ("acquisition", "acquire", "merger")),
    (
        MarketEventType.REGULATORY_ACTION,
        ("sebi", "regulatory action", "penalty", "settlement order"),
    ),
    (MarketEventType.DIVIDEND, ("dividend",)),
    (MarketEventType.BUYBACK, ("buyback", "buy back")),
    (
        MarketEventType.FUNDRAISE,
        ("fund raise", "fundraising", "qualified institutional", "rights issue"),
    ),
    (MarketEventType.INSIDER_TRADING, ("insider trading",)),
    (
        MarketEventType.SHAREHOLDING_CHANGE,
        ("shareholding pattern", "promoter holding"),
    ),
)


def classify_event(item: EvidenceItem) -> MarketEvent:
    haystack = f"{item.title} {item.body}".lower()
    event_type = MarketEventType.UNKNOWN
    for candidate, keywords in _RULES:
        if any(keyword in haystack for keyword in keywords):
            event_type = candidate
            break

    materiality = 0.7 if item.source_tier.value == "OFFICIAL" else 0.5
    return MarketEvent(
        event_type=event_type,
        symbol=item.symbol,
        occurred_at=item.event_at or item.published_at,
        detected_at=item.available_at,
        materiality=materiality,
        evidence_ids=(item.id,),
        summary=item.title,
    )
