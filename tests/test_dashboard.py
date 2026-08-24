from datetime import UTC, datetime

from app.config import AppMode, Settings
from app.dashboard import render_dashboard
from app.dashboard_store import DashboardSnapshotStore, PortfolioSnapshot
from app.models import OrderPlan, Product, Side
from app.persistent_paper import PersistentPaperBroker


def test_dashboard_renders_money_mode_and_no_ai_thoughts(tmp_path) -> None:
    settings = Settings(
        app_mode=AppMode.PAPER,
        starting_cash=100_000,
        data_dir=str(tmp_path),
        _env_file=None,
    )
    broker = PersistentPaperBroker(tmp_path / "paper.sqlite3", starting_cash=100_000)
    broker.place_order(
        OrderPlan(
            intent_id="dashboard-buy",
            symbol="TCS",
            side=Side.BUY,
            product=Product.DELIVERY,
            quantity=10,
            limit_price=1_000,
        )
    )
    store = DashboardSnapshotStore(tmp_path / "dashboard.sqlite3")
    store.append(
        PortfolioSnapshot(
            captured_at=datetime(2026, 8, 25, 4, 0, tzinfo=UTC),
            cash=90_000,
            deployed=10_000,
            holdings_value=11_000,
            total_value=101_000,
        )
    )

    page = render_dashboard(settings)

    assert "PAPER MODE" in page
    assert "₹10,000" in page
    assert "₹101,000" in page
    assert "+1.00% since start" in page
    assert "TCS" in page
    assert "Portfolio value" in page
    assert "AI thinking" not in page
    assert "strategy" not in page.lower()


def test_dashboard_store_preserves_ordered_history(tmp_path) -> None:
    store = DashboardSnapshotStore(tmp_path / "dashboard.sqlite3")
    first = PortfolioSnapshot(
        captured_at=datetime(2026, 8, 25, 3, 0, tzinfo=UTC),
        cash=100_000,
        deployed=0,
        holdings_value=0,
        total_value=100_000,
    )
    second = PortfolioSnapshot(
        captured_at=datetime(2026, 8, 25, 4, 0, tzinfo=UTC),
        cash=90_000,
        deployed=10_000,
        holdings_value=11_000,
        total_value=101_000,
    )
    store.append(first)
    store.append(second)

    assert store.history() == [first, second]
    assert store.latest() == second
