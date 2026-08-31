from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.research_team import FundDecision
from app.stock_memory import StockMemory


THESIS_DRIFT_WINDOW = timedelta(minutes=15)


@dataclass(frozen=True)
class ThesisDriftWarning:
    symbol: str
    previous_action: str
    current_action: str
    previous_recorded_at: datetime
    current_recorded_at: datetime
    elapsed_seconds: float
    previous_confidence: float
    current_confidence: float
    confidence_delta: float
    previous_target_allocation_pct: float
    current_target_allocation_pct: float
    allocation_delta: float
    added_evidence_ids: tuple[str, ...]
    removed_evidence_ids: tuple[str, ...]
    previous_thesis: str
    current_thesis: str

    def as_payload(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "previous_action": self.previous_action,
            "current_action": self.current_action,
            "previous_recorded_at": self.previous_recorded_at.isoformat(),
            "current_recorded_at": self.current_recorded_at.isoformat(),
            "elapsed_seconds": round(self.elapsed_seconds, 1),
            "previous_confidence": self.previous_confidence,
            "current_confidence": self.current_confidence,
            "confidence_delta": round(self.confidence_delta, 4),
            "previous_target_allocation_pct": self.previous_target_allocation_pct,
            "current_target_allocation_pct": self.current_target_allocation_pct,
            "allocation_delta": round(self.allocation_delta, 4),
            "added_evidence_ids": list(self.added_evidence_ids),
            "removed_evidence_ids": list(self.removed_evidence_ids),
            "new_evidence_count": len(self.added_evidence_ids),
            "previous_thesis": self.previous_thesis,
            "current_thesis": self.current_thesis,
            "diagnostic_only": True,
        }


def detect_thesis_drift(
    *,
    previous: StockMemory | None,
    current: FundDecision,
    symbol: str,
    now: datetime,
    window: timedelta = THESIS_DRIFT_WINDOW,
) -> ThesisDriftWarning | None:
    """Flag rapid action reversals without changing the trading decision."""
    if previous is None or now.tzinfo is None or previous.recorded_at.tzinfo is None:
        return None
    current_action = current.action.value.upper()
    previous_action = previous.action.upper()
    if previous_action == current_action:
        return None

    elapsed = (now - previous.recorded_at).total_seconds()
    if elapsed < 0 or elapsed > window.total_seconds():
        return None

    previous_ids = set(previous.evidence_ids)
    current_ids = set(current.evidence_ids)
    return ThesisDriftWarning(
        symbol=symbol.upper(),
        previous_action=previous_action,
        current_action=current_action,
        previous_recorded_at=previous.recorded_at,
        current_recorded_at=now,
        elapsed_seconds=elapsed,
        previous_confidence=previous.confidence,
        current_confidence=current.confidence,
        confidence_delta=current.confidence - previous.confidence,
        previous_target_allocation_pct=previous.target_allocation_pct,
        current_target_allocation_pct=current.target_allocation_pct,
        allocation_delta=current.target_allocation_pct - previous.target_allocation_pct,
        added_evidence_ids=tuple(sorted(current_ids - previous_ids)),
        removed_evidence_ids=tuple(sorted(previous_ids - current_ids)),
        previous_thesis=previous.thesis,
        current_thesis=current.thesis,
    )
