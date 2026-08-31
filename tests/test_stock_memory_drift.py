from datetime import datetime, timedelta, timezone

from app.stock_memory import StockMemory, StockMemoryStore


UTC = timezone.utc


def _memory(
    *,
    at: datetime,
    action: str,
    confidence: float,
    allocation: float,
    evidence_ids: tuple[str, ...],
    thesis: str,
) -> StockMemory:
    return StockMemory(
        id=None,
        symbol="ABC",
        recorded_at=at,
        action=action,
        confidence=confidence,
        target_allocation_pct=allocation,
        horizon="3 months",
        thesis=thesis,
        manager_summary="Manager summary",
        evidence_ids=evidence_ids,
    )


def test_store_persists_rapid_action_reversal_without_blocking_memory(tmp_path) -> None:
    store = StockMemoryStore(tmp_path / "stock-memory.sqlite3")
    first_at = datetime(2026, 8, 31, 4, 0, tzinfo=UTC)

    first_id = store.append(
        _memory(
            at=first_at,
            action="HOLD",
            confidence=0.55,
            allocation=0.0,
            evidence_ids=("old", "shared"),
            thesis="Wait for a cleaner entry.",
        )
    )
    second_id = store.append(
        _memory(
            at=first_at + timedelta(minutes=8),
            action="BUY",
            confidence=0.66,
            allocation=0.025,
            evidence_ids=("shared", "new"),
            thesis="Momentum now supports a small allocation.",
        )
    )

    assert second_id > first_id
    memories = store.recent_for_symbol("ABC")
    assert [item.action for item in memories[:2]] == ["BUY", "HOLD"]

    drift = store.recent_drift()
    assert len(drift) == 1
    payload = drift[0].as_payload()
    assert payload["previous_action"] == "HOLD"
    assert payload["current_action"] == "BUY"
    assert payload["elapsed_seconds"] == 480.0
    assert payload["new_evidence_count"] == 1
    assert payload["added_evidence_ids"] == ["new"]
    assert payload["removed_evidence_ids"] == ["old"]
    assert payload["confidence_delta"] == 0.11
    assert payload["allocation_delta"] == 0.025
    assert payload["diagnostic_only"] is True


def test_store_does_not_flag_same_action_or_slow_revision(tmp_path) -> None:
    store = StockMemoryStore(tmp_path / "stock-memory.sqlite3")
    first_at = datetime(2026, 8, 31, 4, 0, tzinfo=UTC)
    store.append(
        _memory(
            at=first_at,
            action="HOLD",
            confidence=0.55,
            allocation=0.0,
            evidence_ids=("a",),
            thesis="Wait.",
        )
    )
    store.append(
        _memory(
            at=first_at + timedelta(minutes=5),
            action="HOLD",
            confidence=0.60,
            allocation=0.0,
            evidence_ids=("a", "b"),
            thesis="Still wait.",
        )
    )
    store.append(
        _memory(
            at=first_at + timedelta(minutes=25),
            action="BUY",
            confidence=0.65,
            allocation=0.025,
            evidence_ids=("a", "b", "c"),
            thesis="New information supports entry.",
        )
    )

    assert store.recent_drift() == []
