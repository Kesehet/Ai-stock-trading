from datetime import UTC, datetime

from app.fund_status import _position_diagnostics
from app.market_data import HistoricalDataStore
from app.models import Position, Product
from app.portfolio_context import build_portfolio_context


def test_portfolio_context_uses_live_mark_and_cost_basis() -> None:
    context = build_portfolio_context(
        symbol="ABC",
        positions=[
            Position(
                symbol="ABC",
                quantity=10,
                average_price=100.0,
                product=Product.DELIVERY,
            )
        ],
        cash=9000.0,
        market_data=HistoricalDataStore(),
        as_of=datetime(2026, 8, 28, 10, 0, tzinfo=UTC),
        live_prices={"ABC": 95.0},
    )

    assert context.held_quantity == 10
    assert context.average_cost == 100.0
    assert context.mark_price == 95.0
    assert context.unrealized_pnl == -50.0
    assert context.unrealized_pnl_pct == -0.05
    assert round(context.position_weight, 6) == round(950.0 / 9950.0, 6)


def test_position_diagnostics_attributes_current_losers_and_realized_trade() -> None:
    paper = {
        "positions": [
            {
                "symbol": "LOSS",
                "product": "DELIVERY",
                "quantity": 10,
                "average_price": 100.0,
            },
            {
                "symbol": "WIN",
                "product": "DELIVERY",
                "quantity": 5,
                "average_price": 200.0,
            },
        ],
        "orders": [
            {
                "order_id": 9,
                "symbol": "CLOSED",
                "side": "SELL",
                "quantity": 4,
                "price": 120.0,
                "reference_average_price": 110.0,
                "realized_pnl": 38.5,
                "charges": 1.5,
                "executed_at": "2026-08-28T10:00:00+00:00",
            }
        ],
    }
    scanner_state = {
        "updated_at": "2026-08-28T15:29:00+05:30",
        "previous_prices": {"LOSS": 92.0, "WIN": 212.0},
    }

    diagnostics = _position_diagnostics(paper, scanner_state)

    assert diagnostics["mark_updated_at"] == "2026-08-28T15:29:00+05:30"
    assert diagnostics["measured_positions"] == 2
    assert diagnostics["unmeasured_positions"] == 0
    assert diagnostics["unrealized_pnl_total"] == -20.0
    assert diagnostics["material_unrealized_losers"][0]["symbol"] == "LOSS"
    assert diagnostics["material_unrealized_losers"][0]["unrealized_pnl"] == -80.0
    assert diagnostics["unrealized_winners"][0]["symbol"] == "WIN"
    assert diagnostics["recent_realized_trades"][0]["outcome"] == "win"
    assert diagnostics["recent_realized_trades"][0]["realized_pnl"] == 38.5
