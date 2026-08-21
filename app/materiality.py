from __future__ import annotations

from dataclasses import dataclass

from app.evidence.classifier import classify_event
from app.evidence.models import EvidenceItem, MarketEventType, SourceTier


_EVENT_BASE: dict[MarketEventType, float] = {
    MarketEventType.FINANCIAL_RESULTS: 0.85,
    MarketEventType.MANAGEMENT_CHANGE: 0.70,
    MarketEventType.LARGE_ORDER: 0.80,
    MarketEventType.ACQUISITION: 0.85,
    MarketEventType.REGULATORY_ACTION: 0.90,
    MarketEventType.DIVIDEND: 0.55,
    MarketEventType.BUYBACK: 0.75,
    MarketEventType.FUNDRAISE: 0.75,
    MarketEventType.INSIDER_TRADING: 0.70,
    MarketEventType.SHAREHOLDING_CHANGE: 0.60,
    MarketEventType.BOARD_MEETING: 0.45,
    MarketEventType.CORPORATE_ACTION: 0.55,
    MarketEventType.UNKNOWN: 0.30,
}

_TIER_WEIGHT: dict[SourceTier, float] = {
    SourceTier.OFFICIAL: 1.00,
    SourceTier.PRIMARY: 0.95,
    SourceTier.WIRE: 0.90,
    SourceTier.NEWS: 0.75,
    SourceTier.SOCIAL: 0.45,
}


@dataclass(frozen=True)
class MaterialityScore:
    value: float
    event_type: MarketEventType
    rationale: str


def score_evidence(item: EvidenceItem) -> MaterialityScore:
    event = classify_event(item)
    base = _EVENT_BASE[event.event_type]
    source_weight = _TIER_WEIGHT[item.source_tier]
    trust_weight = 0.5 + (item.trust_score * 0.5)
    value = min(1.0, max(0.0, base * source_weight * trust_weight))
    return MaterialityScore(
        value=value,
        event_type=event.event_type,
        rationale=(
            f"base={base:.2f}; source={item.source_tier}; "
            f"trust={item.trust_score:.2f}"
        ),
    )
