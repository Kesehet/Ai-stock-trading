from datetime import date

import pytest

from app.costs import CostScheduleRegistry, ZERODHA_NSE_CASH_2026
from app.models import Product, Side


def test_delivery_costs_include_stt_exchange_gst_and_stamp() -> None:
    charges = ZERODHA_NSE_CASH_2026.charges(
        turnover=100_000,
        side=Side.BUY,
        product=Product.DELIVERY,
    )

    assert charges > 100
    assert charges < 200


def test_intraday_brokerage_is_capped_per_executed_order() -> None:
    charges = ZERODHA_NSE_CASH_2026.charges(
        turnover=1_000_000,
        side=Side.BUY,
        product=Product.INTRADAY,
        executed_orders=1,
    )

    uncapped_brokerage = 1_000_000 * 0.0003
    assert uncapped_brokerage == 300
    assert charges < 100


def test_registry_rejects_dates_before_first_schedule() -> None:
    registry = CostScheduleRegistry([ZERODHA_NSE_CASH_2026])

    with pytest.raises(ValueError):
        registry.for_date(date(2025, 12, 31))
