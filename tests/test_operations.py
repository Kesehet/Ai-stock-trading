from datetime import UTC, datetime

from app.operations import OperationsStore


def test_safe_mode_persists_and_is_audited(tmp_path) -> None:
    path = tmp_path / "operations.sqlite3"
    store = OperationsStore(path)
    when = datetime(2026, 8, 25, 1, 0, tzinfo=UTC)

    state = store.set_safe_mode(True, "TEST_TRIP", when)

    assert state.safe_mode is True
    reopened = OperationsStore(path)
    assert reopened.get_safety_state().reason == "TEST_TRIP"
    events = reopened.recent_events()
    assert events[0]["action"] == "SAFE_MODE_ENABLED"
    assert events[0]["payload"] == {"reason": "TEST_TRIP"}


def test_safe_mode_requires_reason(tmp_path) -> None:
    store = OperationsStore(tmp_path / "operations.sqlite3")

    try:
        store.set_safe_mode(True, "")
    except ValueError as exc:
        assert "requires a reason" in str(exc)
    else:
        raise AssertionError("safe mode accepted an empty reason")
