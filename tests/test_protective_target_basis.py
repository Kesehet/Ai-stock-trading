from datetime import UTC, datetime

from app.hardened_trader import HardenedProductionAutonomousTrader
from app.models import Position, Product, Quote, Side


def test_protective_target_must_clear_actual_managed_position_basis() -> None:
    position = Position(
        symbol="CGCL",
        quantity=100,
        average_price=256.18,
        product=Product.DELIVERY,
    )

    assert (
        HardenedProductionAutonomousTrader._target_is_profitable(position, 256.06)
        is False
    )
    assert (
        HardenedProductionAutonomousTrader._target_is_profitable(position, 256.18)
        is False
    )
    assert (
        HardenedProductionAutonomousTrader._target_is_profitable(position, 260.00)
        is True
    )
    assert (
        HardenedProductionAutonomousTrader._target_is_profitable(position, None)
        is False
    )


def test_flat_symbol_research_cooldown_penalizes_non_executable_sell() -> None:
    base = 900

    assert (
        HardenedProductionAutonomousTrader._flat_symbol_cooldown_seconds(
            Side.SELL.value, base
        )
        == 3600
    )
    assert (
        HardenedProductionAutonomousTrader._flat_symbol_cooldown_seconds(
            Side.HOLD.value, base
        )
        == 1800
    )
    assert (
        HardenedProductionAutonomousTrader._flat_symbol_cooldown_seconds(
            Side.BUY.value, base
        )
        == 900
    )


def test_tiny_delivery_position_is_not_worth_carrying_when_dp_cost_eats_target() -> None:
    now = datetime.now(UTC)
    position = Position(
        symbol="JINDWORLD",
        quantity=1,
        average_price=42.74,
        product=Product.DELIVERY,
    )
    quote = Quote(symbol="JINDWORLD", last_price=42.08, as_of=now)

    reward, downside, reward_risk, future_exit_cost = (
        HardenedProductionAutonomousTrader._overnight_cost_metrics(
            position,
            quote,
            stop_price=40.0,
            target_price=46.0,
        )
    )

    assert reward < 0
    assert downside > 0
    assert reward_risk < 1.5
    assert future_exit_cost > 15.0


def test_larger_delivery_position_can_clear_cost_adjusted_overnight_threshold() -> None:
    now = datetime.now(UTC)
    position = Position(
        symbol="VIABLE",
        quantity=5,
        average_price=100.0,
        product=Product.DELIVERY,
    )
    quote = Quote(symbol="VIABLE", last_price=100.0, as_of=now)

    reward, downside, reward_risk, future_exit_cost = (
        HardenedProductionAutonomousTrader._overnight_cost_metrics(
            position,
            quote,
            stop_price=95.0,
            target_price=140.0,
        )
    )

    assert reward > 0
    assert downside > 0
    assert reward_risk >= 1.5
    assert future_exit_cost > 15.0
