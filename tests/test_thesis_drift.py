from datetime import datetime, timedelta, timezone

from app.models import Side
from app.research_team import FundDecision
from app.stock_memory import StockMemory
from app.thesis_drift import detect_thesis_drift


UTC = timezone.utc


def _memory(*, action: str = "HOLD") -> StockMemory:
    return StockMemory(
        id=1,
        symbol="ABC",
        recorded_at=datetime(2026, 8, 31, 4, 0, tzinfo=UTC),
        action=action,
        confidence=0.55,
        target_allocation_pct=0.0,
        horizon="short-term",
        thesis="Wait for better reward to risk.",
        manager_summary="Mixed evidence.",
        evidence_ids=("old", "shared"),
    )


def _decision(*, action: Side = Side.BUY) -> FundDecision:
    return FundDecision(
        action=action,
        target_allocation_pct=0.025 if action == Side.BUY else 0.0,
        confidence=0.66,
        horizon="3 months",
        thesis="Momentum now supports a small allocation.",
        evidence_ids=("shared", "new"),
    )


def test_detects_rapid_action_reversal_and_compares_evidence() -> None:
    warning = detect_thesis_drift(
        previous=_memory(),
        current=_decision(),
        symbol="abc",
        now=datetime(2026, 8, 31, 4, 8, tzinfo=UTC),
    )

    assert warning is not None
    payload = warning.as_payload()
    assert payload["previous_action"] == "HOLD"
    assert payload["current_action"] == "BUY"
    assert payload["new_evidence_count"] == 1
    assert payload["added_evidence_ids"] == ["new"]
    assert payload["removed_evidence_ids"] == ["old"]
    assert payload["confidence_delta"] == 0.11
    assert payload["diagnostic_only"] is True


def test_same_action_is_not_drift() -> None:
    assert (
        detect_thesis_drift(
            previous=_memory(action="BUY"),
            current=_decision(action=Side.BUY),
            symbol="ABC",
            now=datetime(2026, 8, 31, 4, 8, tzinfo=UTC),
        )
        is None
    )


def test_old_reversal_is_not_rapid_drift() -> None:
    assert (
        detect_thesis_drift(
            previous=_memory(),
            current=_decision(),
            symbol="ABC",
            now=datetime(2026, 8, 31, 4, 0, tzinfo=UTC) + timedelta(minutes=16),
        )
        is None
    )
