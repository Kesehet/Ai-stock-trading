from datetime import UTC, datetime, timedelta

import pytest

from app.theses import Thesis, ThesisStore


def test_thesis_survives_restart_and_closes_with_reason(tmp_path) -> None:
    path = tmp_path / "theses.sqlite3"
    created = datetime(2026, 8, 25, 9, 0, tzinfo=UTC)
    thesis = Thesis(
        thesis_id="tcs-1",
        symbol="TCS",
        strategy_id="multi_agent_fund_v2",
        created_at=created,
        data_cutoff_at=created,
        horizon="2-8 weeks",
        thesis="Revenue growth and technical trend are supportive.",
        evidence_ids=("e1", "e2"),
    )
    store = ThesisStore(path)
    store.create(thesis)

    restarted = ThesisStore(path)
    assert restarted.get("tcs-1") == thesis
    assert restarted.open_for_symbol("TCS") == [thesis]

    closed = restarted.close(
        "tcs-1",
        created + timedelta(days=10),
        "Target thesis completed",
    )
    assert closed.status == "CLOSED"
    assert closed.close_reason == "Target thesis completed"
    assert restarted.open_for_symbol("TCS") == []


def test_thesis_rejects_future_data_cutoff(tmp_path) -> None:
    created = datetime(2026, 8, 25, 9, 0, tzinfo=UTC)
    store = ThesisStore(tmp_path / "theses.sqlite3")

    with pytest.raises(ValueError, match="cutoff"):
        store.create(
            Thesis(
                thesis_id="bad",
                symbol="TCS",
                strategy_id="test",
                created_at=created,
                data_cutoff_at=created + timedelta(seconds=1),
                horizon="test",
                thesis="bad future data",
                evidence_ids=(),
            )
        )
