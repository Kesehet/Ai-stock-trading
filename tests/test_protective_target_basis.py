from datetime import UTC, datetime

from app.hardened_trader import HardenedProductionAutonomousTrader
from app.models import Position, Product, Quote, Side
from app.risk import PortfolioSnapshot


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


def test_flat_expensive_symbol_is_skipped_before_ai_research() -> None:
    now = datetime.now(UTC)
    quote = Quote(symbol="ENGINERSIN", last_price=281.10, as_of=now)
    portfolio = PortfolioSnapshot(
        cash=438.0,
        equity=480.0,
        open_positions=1,
        positions=(
            Position(
                symbol="JINDWORLD",
                quantity=1,
                average_price=42.79,
                product=Product.DELIVERY,
            ),
        ),
    )

    reason = HardenedProductionAutonomousTrader._fresh_entry_block_reason(
        "ENGINERSIN",
        quote,
        portfolio,
        max_position_pct=0.50,
        max_open_positions=3,
    )

    assert reason == "One share exceeds available cash or maximum position budget"


def test_affordable_flat_symbol_remains_eligible_for_ai_research() -> None:
    now = datetime.now(UTC)
    quote = Quote(symbol="TNPETRO", last_price=129.0, as_of=now)
    portfolio = PortfolioSnapshot(
        cash=438.0,
        equity=480.0,
        open_positions=1,
        positions=(
            Position(
                symbol="JINDWORLD",
                quantity=1,
                average_price=42.79,
                product=Product.DELIVERY,
            ),
        ),
    )

    reason = HardenedProductionAutonomousTrader._fresh_entry_block_reason(
        "TNPETRO",
        quote,
        portfolio,
        max_position_pct=0.50,
        max_open_positions=3,
    )

    assert reason == ""


def test_expensive_held_symbol_is_never_filtered_from_risk_review() -> None:
    now = datetime.now(UTC)
    quote = Quote(symbol="EXPENSIVE", last_price=650.0, as_of=now)
    portfolio = PortfolioSnapshot(
        cash=100.0,
        equity=750.0,
        open_positions=1,
        positions=(
            Position(
                symbol="EXPENSIVE",
                quantity=1,
                average_price=640.0,
                product=Product.DELIVERY,
            ),
        ),
    )

    reason = HardenedProductionAutonomousTrader._fresh_entry_block_reason(
        "EXPENSIVE",
        quote,
        portfolio,
        max_position_pct=0.50,
        max_open_positions=3,
    )

    assert reason == ""


def test_new_symbol_is_skipped_when_position_slots_are_full() -> None:
    now = datetime.now(UTC)
    quote = Quote(symbol="CHEAP", last_price=30.0, as_of=now)
    portfolio = PortfolioSnapshot(
        cash=300.0,
        equity=500.0,
        open_positions=3,
        positions=(
            Position(
                symbol="A",
                quantity=1,
                average_price=50.0,
                product=Product.DELIVERY,
            ),
            Position(
                symbol="B",
                quantity=1,
                average_price=50.0,
                product=Product.DELIVERY,
            ),
            Position(
                symbol="C",
                quantity=1,
                average_price=50.0,
                product=Product.DELIVERY,
            ),
        ),
    )

    reason = HardenedProductionAutonomousTrader._fresh_entry_block_reason(
        "CHEAP",
        quote,
        portfolio,
        max_position_pct=0.50,
        max_open_positions=3,
    )

    assert reason == "Maximum open positions reached"


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
