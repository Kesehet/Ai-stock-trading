import pytest

from app.models import OrderPlan, Product, Side
from app.persistent_paper import PersistentPaperBroker


def _buy_plan(intent_id: str = "intent-1") -> OrderPlan:
    return OrderPlan(
        intent_id=intent_id,
        symbol="TCS",
        side=Side.BUY,
        product=Product.DELIVERY,
        quantity=10,
        limit_price=100,
    )


def test_paper_account_and_positions_survive_restart(tmp_path) -> None:
    path = tmp_path / "paper.sqlite3"
    broker = PersistentPaperBroker(path, starting_cash=100_000)

    result = broker.place_order(_buy_plan())
    restarted = PersistentPaperBroker(path, starting_cash=100_000)

    assert result.status == "FILLED"
    assert restarted.get_cash() == pytest.approx(99_000)
    positions = restarted.get_positions()
    assert len(positions) == 1
    assert positions[0].symbol == "TCS"
    assert positions[0].quantity == 10
    assert positions[0].average_price == pytest.approx(100)


def test_changing_starting_cash_resets_only_paper_ledger(tmp_path) -> None:
    path = tmp_path / "paper.sqlite3"
    broker = PersistentPaperBroker(path, starting_cash=100_000)
    broker.place_order(_buy_plan())

    reset = PersistentPaperBroker(path, starting_cash=500)

    assert reset.get_cash() == pytest.approx(500)
    assert reset.get_positions() == []


def test_duplicate_intent_is_idempotent(tmp_path) -> None:
    path = tmp_path / "paper.sqlite3"
    broker = PersistentPaperBroker(path, starting_cash=100_000)
    plan = _buy_plan()

    first = broker.place_order(plan)
    second = broker.place_order(plan)

    assert second == first
    assert broker.get_cash() == pytest.approx(99_000)
    assert broker.get_positions()[0].quantity == 10


def test_sell_updates_persistent_position_and_cash(tmp_path) -> None:
    broker = PersistentPaperBroker(tmp_path / "paper.sqlite3", starting_cash=100_000)
    broker.place_order(_buy_plan())
    sell = OrderPlan(
        intent_id="intent-2",
        symbol="TCS",
        side=Side.SELL,
        product=Product.DELIVERY,
        quantity=4,
        limit_price=110,
    )

    broker.place_order(sell)

    assert broker.get_cash() == pytest.approx(99_440)
    assert broker.get_positions()[0].quantity == 6
