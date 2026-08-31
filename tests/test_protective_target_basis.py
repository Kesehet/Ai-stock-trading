from app.hardened_trader import HardenedProductionAutonomousTrader
from app.models import Position, Product


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
