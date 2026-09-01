from datetime import UTC, datetime

import pytest

from app.costs import ZERODHA_NSE_CASH_2026
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


def _sell_plan(intent_id: str = "intent-2", quantity: int = 10, price: float = 110) -> OrderPlan:
    return OrderPlan(
        intent_id=intent_id,
        symbol="TCS",
        side=Side.SELL,
        product=Product.DELIVERY,
        quantity=quantity,
        limit_price=price,
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
    broker.place_order(_sell_plan(quantity=4))

    assert broker.get_cash() == pytest.approx(99_440)
    assert broker.get_positions()[0].quantity == 6


def test_same_day_cnc_round_trip_uses_intraday_economics_without_dp(tmp_path) -> None:
    broker = PersistentPaperBroker(
        tmp_path / "paper.sqlite3",
        starting_cash=500,
        charge_schedule=ZERODHA_NSE_CASH_2026,
    )
    broker._now = lambda: datetime(2026, 9, 1, 4, 30, tzinfo=UTC)
    buy = OrderPlan(
        intent_id="manali-buy",
        symbol="MANALIPETC",
        side=Side.BUY,
        product=Product.DELIVERY,
        quantity=1,
        limit_price=87.04,
    )
    broker.place_order(buy)

    broker._now = lambda: datetime(2026, 9, 1, 9, 37, tzinfo=UTC)
    sell = OrderPlan(
        intent_id="manali-sell",
        symbol="MANALIPETC",
        side=Side.SELL,
        product=Product.DELIVERY,
        quantity=1,
        limit_price=83.39,
    )
    broker.place_order(sell)

    expected_buy_charges = ZERODHA_NSE_CASH_2026.charges(
        turnover=87.04,
        side=Side.BUY,
        product=Product.INTRADAY,
    )
    expected_sell_charges = ZERODHA_NSE_CASH_2026.charges(
        turnover=83.39,
        side=Side.SELL,
        product=Product.INTRADAY,
    )
    expected_cash = 500 - 87.04 - expected_buy_charges + 83.39 - expected_sell_charges

    assert broker.get_cash() == pytest.approx(expected_cash)
    assert broker.get_positions() == []
    assert 495 < broker.get_cash() < 497


def test_overnight_delivery_sell_applies_dp_charge(tmp_path) -> None:
    broker = PersistentPaperBroker(
        tmp_path / "paper.sqlite3",
        starting_cash=500,
        charge_schedule=ZERODHA_NSE_CASH_2026,
    )
    broker._now = lambda: datetime(2026, 9, 1, 4, 30, tzinfo=UTC)
    buy = OrderPlan(
        intent_id="overnight-buy",
        symbol="MANALIPETC",
        side=Side.BUY,
        product=Product.DELIVERY,
        quantity=1,
        limit_price=87.04,
    )
    broker.place_order(buy)

    broker._now = lambda: datetime(2026, 9, 2, 4, 30, tzinfo=UTC)
    sell = OrderPlan(
        intent_id="overnight-sell",
        symbol="MANALIPETC",
        side=Side.SELL,
        product=Product.DELIVERY,
        quantity=1,
        limit_price=87.04,
    )
    broker.place_order(sell)

    buy_charges = ZERODHA_NSE_CASH_2026.charges(
        turnover=87.04,
        side=Side.BUY,
        product=Product.DELIVERY,
    )
    sell_charges = ZERODHA_NSE_CASH_2026.charges(
        turnover=87.04,
        side=Side.SELL,
        product=Product.DELIVERY,
        include_dp=True,
    )
    expected_cash = 500 - 87.04 - buy_charges + 87.04 - sell_charges

    assert broker.get_cash() == pytest.approx(expected_cash)
    assert sell_charges > 15


def test_dp_charge_is_applied_once_per_symbol_per_day(tmp_path) -> None:
    broker = PersistentPaperBroker(
        tmp_path / "paper.sqlite3",
        starting_cash=1_000,
        charge_schedule=ZERODHA_NSE_CASH_2026,
    )
    broker._now = lambda: datetime(2026, 9, 1, 4, 30, tzinfo=UTC)
    broker.place_order(_buy_plan(quantity=10) if False else OrderPlan(
        intent_id="ten-buy",
        symbol="TCS",
        side=Side.BUY,
        product=Product.DELIVERY,
        quantity=5,
        limit_price=100,
    ))

    broker._now = lambda: datetime(2026, 9, 2, 4, 30, tzinfo=UTC)
    broker.place_order(_sell_plan(intent_id="sell-a", quantity=2, price=100))
    cash_after_first = broker.get_cash()
    broker.place_order(_sell_plan(intent_id="sell-b", quantity=2, price=100))
    cash_after_second = broker.get_cash()

    first_proceeds = cash_after_first - (1_000 - 500 - ZERODHA_NSE_CASH_2026.charges(
        turnover=500,
        side=Side.BUY,
        product=Product.DELIVERY,
    ))
    second_proceeds = cash_after_second - cash_after_first

    assert second_proceeds - first_proceeds > 15
