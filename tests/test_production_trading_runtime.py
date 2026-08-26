from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.costs import ZERODHA_NSE_CASH_2026
from app.live_order_ledger import LiveOrderLedger
from app.models import OrderPlan, Position, Product, Quote, Side, TradeIntent
from app.persistent_paper import PersistentPaperBroker
from app.position_policy import PositionPolicyStore
from app.risk import PortfolioSnapshot, RiskEngine, RiskLimits
from app.runtime_mode import RuntimeModeStore
from app.config import AppMode


def _intent(
    *,
    side: Side,
    allocation: float,
    confidence: float = 0.9,
    now: datetime,
) -> TradeIntent:
    return TradeIntent(
        symbol="TCS",
        side=side,
        product=Product.DELIVERY,
        thesis_id="test-thesis",
        strategy_id="test-strategy",
        target_allocation_pct=allocation,
        confidence=confidence,
        horizon="swing",
        decision_at=now,
        data_cutoff_at=now,
    )


def test_buy_sizes_toward_target_instead_of_accumulating() -> None:
    now = datetime(2026, 8, 27, 4, 0, tzinfo=UTC)
    risk = RiskEngine(RiskLimits(max_position_pct=0.05))
    quote = Quote(symbol="TCS", last_price=100, as_of=now)
    portfolio = PortfolioSnapshot(
        cash=95_000,
        equity=100_000,
        open_positions=1,
        positions=(
            Position(
                symbol="TCS",
                quantity=50,
                average_price=100,
                product=Product.DELIVERY,
            ),
        ),
    )

    decision = risk.evaluate(
        _intent(side=Side.BUY, allocation=0.05, now=now),
        quote,
        portfolio,
        now=now,
    )

    assert decision.approved is False
    assert "already" in decision.reason.lower()


def test_sell_can_exit_after_daily_loss_limit_and_only_held_quantity() -> None:
    now = datetime(2026, 8, 27, 4, 0, tzinfo=UTC)
    risk = RiskEngine(RiskLimits(max_daily_loss_pct=0.01))
    quote = Quote(symbol="TCS", last_price=100, as_of=now)
    held = Position(
        symbol="TCS",
        quantity=7,
        average_price=110,
        product=Product.DELIVERY,
    )
    portfolio = PortfolioSnapshot(
        cash=50_000,
        equity=50_700,
        open_positions=1,
        daily_pnl=-2_000,
        positions=(held,),
    )

    decision = risk.evaluate(
        _intent(side=Side.SELL, allocation=0.0, now=now),
        quote,
        portfolio,
        now=now,
    )

    assert decision.approved is True
    assert decision.order_plan is not None
    assert decision.order_plan.quantity == 7


def test_low_confidence_buy_is_rejected() -> None:
    now = datetime(2026, 8, 27, 4, 0, tzinfo=UTC)
    risk = RiskEngine(RiskLimits(min_buy_confidence=0.60))
    quote = Quote(symbol="TCS", last_price=100, as_of=now)
    portfolio = PortfolioSnapshot(cash=100_000, equity=100_000, open_positions=0)

    decision = risk.evaluate(
        _intent(side=Side.BUY, allocation=0.05, confidence=0.59, now=now),
        quote,
        portfolio,
        now=now,
    )

    assert decision.approved is False
    assert "confidence" in decision.reason.lower()


def test_paper_broker_applies_slippage_and_realistic_charges(tmp_path: Path) -> None:
    broker = PersistentPaperBroker(
        tmp_path / "paper.sqlite3",
        starting_cash=100_000,
        slippage_bps=5,
        charge_schedule=ZERODHA_NSE_CASH_2026,
    )
    buy = broker.place_order(
        OrderPlan(
            intent_id="buy-1",
            symbol="TCS",
            side=Side.BUY,
            product=Product.DELIVERY,
            quantity=10,
            limit_price=100,
        )
    )
    assert buy.average_price > 100
    assert broker.get_cash() < 99_000

    sell = broker.place_order(
        OrderPlan(
            intent_id="sell-1",
            symbol="TCS",
            side=Side.SELL,
            product=Product.DELIVERY,
            quantity=10,
            limit_price=100,
        )
    )
    assert sell.average_price < 100
    assert broker.get_cash() < 100_000


def test_live_ledger_is_idempotent_and_tracks_partial_fills(tmp_path: Path) -> None:
    ledger = LiveOrderLedger(tmp_path / "live.sqlite3")
    plan = OrderPlan(
        intent_id="live-buy-1",
        symbol="TCS",
        side=Side.BUY,
        product=Product.DELIVERY,
        quantity=10,
        limit_price=100,
    )
    assert ledger.claim(plan) is True
    assert ledger.claim(plan) is False

    ledger.update(
        plan.intent_id,
        broker_order_id="zerodha-1",
        status="OPEN",
        filled_quantity=4,
        average_price=101,
    )
    positions = ledger.managed_positions()
    assert len(positions) == 1
    assert positions[0].quantity == 4
    assert positions[0].average_price == 101


def test_live_ledger_never_exposes_unrelated_broker_holdings(tmp_path: Path) -> None:
    ledger = LiveOrderLedger(tmp_path / "live.sqlite3")
    assert ledger.managed_positions() == []
    assert ledger.managed_cash(500_000) == 500_000


def test_position_policy_persists_stop_and_target(tmp_path: Path) -> None:
    store = PositionPolicyStore(tmp_path / "policies.sqlite3")
    store.set(
        symbol="TCS",
        product=Product.DELIVERY,
        stop_price=95,
        target_price=120,
        thesis_id="thesis-1",
    )
    policy = store.get("TCS", Product.DELIVERY)
    assert policy is not None
    assert policy.stop_price == 95
    assert policy.target_price == 120


def test_admin_runtime_mode_is_persistent(tmp_path: Path) -> None:
    store = RuntimeModeStore(tmp_path / "runtime-mode.json", default_mode=AppMode.PAPER)
    assert store.load().mode == AppMode.PAPER
    store.save(AppMode.LIVE)
    assert store.load().mode == AppMode.LIVE


def test_runtime_mode_rejects_backtest_as_continuous_mode(tmp_path: Path) -> None:
    store = RuntimeModeStore(tmp_path / "runtime-mode.json")
    with pytest.raises(ValueError):
        store.save(AppMode.BACKTEST)
