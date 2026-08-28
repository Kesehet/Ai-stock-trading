from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import Settings
from app.dashboard_store import DashboardSnapshotStore
from app.nse_calendar import nse_capital_market_calendar
from app.operations import OperationsStore
from app.runtime_mode import RuntimeModeStore
from app.scheduler import IST


def _safe_event(event: dict[str, Any]) -> dict[str, Any]:
    payload = event.get("payload")
    return {
        "id": event.get("id"),
        "created_at": event.get("created_at"),
        "category": event.get("category"),
        "action": event.get("action"),
        "payload": payload if isinstance(payload, dict) else {},
    }


def _tail_text(path: Path, lines: int = 300) -> list[str]:
    if not path.exists():
        return []
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return content.splitlines()[-lines:]


def _read_json(path: Path) -> object | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _paper_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"positions": [], "orders": [], "realized_pnl": 0.0, "charges": 0.0}
    connection = sqlite3.connect(path, timeout=5)
    connection.row_factory = sqlite3.Row
    try:
        positions = [
            dict(row)
            for row in connection.execute(
                """
                SELECT symbol, product, quantity, average_price
                FROM positions ORDER BY symbol, product
                """
            ).fetchall()
        ]
        orders = [
            dict(row)
            for row in connection.execute(
                """
                SELECT order_id, intent_id, symbol, side, product, quantity, price,
                       status, filled_quantity, executed_at, realized_pnl,
                       reference_average_price, charges
                FROM paper_orders
                ORDER BY order_id DESC
                LIMIT 200
                """
            ).fetchall()
        ]
        aggregate = connection.execute(
            """
            SELECT COALESCE(SUM(realized_pnl), 0) AS realized_pnl,
                   COALESCE(SUM(charges), 0) AS charges
            FROM paper_orders
            """
        ).fetchone()
        cash_row = connection.execute(
            "SELECT cash FROM account WHERE singleton_id = 1"
        ).fetchone()
        return {
            "cash": float(cash_row["cash"]) if cash_row is not None else None,
            "positions": positions,
            "orders": orders,
            "realized_pnl": round(float(aggregate["realized_pnl"]), 2)
            if aggregate is not None
            else 0.0,
            "charges": round(float(aggregate["charges"]), 2)
            if aggregate is not None
            else 0.0,
        }
    finally:
        connection.close()


def _event_diagnostics(events: list[dict[str, Any]]) -> dict[str, Any]:
    action_counts = Counter(str(item.get("action", "")) for item in events)
    category_counts = Counter(str(item.get("category", "")) for item in events)
    per_symbol: dict[str, Counter[str]] = defaultdict(Counter)
    for item in events:
        payload = item.get("payload")
        if not isinstance(payload, dict):
            continue
        symbol = payload.get("symbol")
        if isinstance(symbol, str) and symbol:
            per_symbol[symbol][str(item.get("action", ""))] += 1
    return {
        "action_counts": dict(action_counts),
        "category_counts": dict(category_counts),
        "per_symbol_action_counts": {
            symbol: dict(counter) for symbol, counter in sorted(per_symbol.items())
        },
    }


def build_fund_status(settings: Settings, now: datetime | None = None) -> dict[str, Any]:
    current = (now or datetime.now(IST)).astimezone(IST)
    data_dir = Path(settings.data_dir)
    dashboard = DashboardSnapshotStore(data_dir / "dashboard.sqlite3")
    operations = OperationsStore(data_dir / "operations.sqlite3")
    mode = RuntimeModeStore(
        data_dir / "runtime-mode.json", default_mode=settings.app_mode
    ).load().mode

    nav_history = dashboard.history(limit=720)
    latest = nav_history[-1] if nav_history else None
    today = [item for item in nav_history if item.captured_at.astimezone(IST).date() == current.date()]
    day_start = today[0] if today else None

    audit_events = [_safe_event(item) for item in operations.recent_events(limit=300)]
    safety = operations.get_safety_state()
    paper = _paper_state(data_dir / "paper.sqlite3")

    heartbeat = Path(settings.heartbeat_path)
    heartbeat_age_seconds: float | None = None
    if heartbeat.exists():
        heartbeat_age_seconds = max(0.0, current.timestamp() - heartbeat.stat().st_mtime)

    total_value = latest.total_value if latest else settings.starting_cash
    pnl_total = total_value - settings.starting_cash
    pnl_today = total_value - day_start.total_value if day_start else 0.0
    nav_payload = [
        {
            "captured_at": item.captured_at.isoformat(),
            "cash": round(item.cash, 2),
            "deployed": round(item.deployed, 2),
            "holdings_value": round(item.holdings_value, 2),
            "total_value": round(item.total_value, 2),
        }
        for item in nav_history
    ]

    decisions = [item for item in audit_events if item["action"] == "FUND_DECISION"]
    failures = [
        item
        for item in audit_events
        if item["action"]
        in {
            "RESEARCH_FAILED",
            "NEWS_REFRESH_FAILED",
            "ORDER_FAILED",
            "PROTECTIVE_EXIT_FAILED",
            "ZERODHA_UNAVAILABLE",
            "TICK_FAILED",
            "INTRADAY_SCAN_FAILED",
        }
    ]
    risk_events = [item for item in audit_events if item["category"] == "risk"]
    execution_events = [item for item in audit_events if item["category"] == "execution"]
    scan_events = [
        item for item in audit_events if item["action"] == "INTRADAY_OPPORTUNITY_SCAN"
    ]

    return {
        "schema_version": 2,
        "generated_at": current.isoformat(),
        "mode": mode.value,
        "market_phase": nse_capital_market_calendar(current).phase_at(current).value,
        "worker": {
            "heartbeat_age_seconds": round(heartbeat_age_seconds, 1)
            if heartbeat_age_seconds is not None
            else None,
            "healthy": heartbeat_age_seconds is not None and heartbeat_age_seconds <= 90,
        },
        "safety": {
            "safe_mode": safety.safe_mode,
            "reason": safety.reason,
            "updated_at": safety.updated_at.isoformat(),
        },
        "portfolio": {
            "starting_cash": settings.starting_cash,
            "cash": round(latest.cash, 2) if latest else settings.starting_cash,
            "deployed": round(latest.deployed, 2) if latest else 0.0,
            "holdings_value": round(latest.holdings_value, 2) if latest else 0.0,
            "total_value": round(total_value, 2),
            "pnl_total": round(pnl_total, 2),
            "pnl_total_pct": round((pnl_total / settings.starting_cash) * 100, 4),
            "pnl_today": round(pnl_today, 2),
            "realized_pnl": paper["realized_pnl"],
            "paper_charges": paper["charges"],
        },
        "paper_broker": paper,
        "nav_history": nav_payload,
        "runtime_state": _read_json(data_dir / "runtime-state.json"),
        "diagnostics": {
            **_event_diagnostics(audit_events),
            "recent_decisions": decisions[:40],
            "recent_failures": failures[:40],
            "recent_risk_events": risk_events[:60],
            "recent_execution_events": execution_events[:60],
            "recent_intraday_scans": scan_events[:20],
            "audit_events": audit_events,
            "trader_log_tail": _tail_text(data_dir / "trader-diagnostics.log", 300),
            "trader_log_previous_tail": _tail_text(
                data_dir / "trader-diagnostics.log.1", 120
            ),
        },
        "active_configuration": {
            "dynamic_universe": settings.dynamic_universe,
            "decision_interval_seconds": settings.decision_interval_seconds,
            "quote_poll_seconds": settings.quote_poll_seconds,
            "max_ai_candidates": settings.max_ai_candidates,
            "max_position_pct": settings.max_position_pct,
            "max_daily_loss_pct": settings.max_daily_loss_pct,
            "max_open_positions": settings.max_open_positions,
            "min_buy_confidence": settings.min_buy_confidence,
            "paper_slippage_bps": settings.paper_slippage_bps,
            "universe_scan_limit": settings.universe_scan_limit,
            "intraday_scanner_enabled": settings.intraday_scanner_enabled,
            "intraday_scan_interval_seconds": settings.intraday_scan_interval_seconds,
            "intraday_scan_pool_limit": settings.intraday_scan_pool_limit,
            "intraday_hot_candidates": settings.intraday_hot_candidates,
            "intraday_hot_score_min": settings.intraday_hot_score_min,
            "intraday_interrupt_cooldown_seconds": settings.intraday_interrupt_cooldown_seconds,
        },
    }
