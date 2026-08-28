from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import Settings
from app.dashboard_store import DashboardSnapshotStore
from app.nse_calendar import nse_capital_market_calendar
from app.operations import OperationsStore
from app.runtime_mode import RuntimeModeStore
from app.scheduler import IST


_ALLOWED_ACTIONS = {
    "MODE_ACTIVE",
    "DYNAMIC_NSE_UNIVERSE_WARMED",
    "CANDIDATES_SELECTED",
    "INTRADAY_OPPORTUNITY_SCAN",
    "FUND_DECISION",
    "RESEARCH_FAILED",
    "NEWS_REFRESH_FAILED",
    "APPROVED",
    "REJECTED",
    "ORDER_ACCEPTED",
    "ORDER_FAILED",
    "PROTECTIVE_EXIT",
    "PROTECTIVE_EXIT_FAILED",
    "DAILY_LOSS_LIMIT_ACTIVE",
    "ZERODHA_UNAVAILABLE",
}


def _safe_event(event: dict[str, Any]) -> dict[str, Any]:
    payload = event.get("payload")
    return {
        "created_at": event.get("created_at"),
        "category": event.get("category"),
        "action": event.get("action"),
        "payload": payload if isinstance(payload, dict) else {},
    }


def build_fund_status(settings: Settings, now: datetime | None = None) -> dict[str, Any]:
    current = (now or datetime.now(IST)).astimezone(IST)
    data_dir = Path(settings.data_dir)
    dashboard = DashboardSnapshotStore(data_dir / "dashboard.sqlite3")
    operations = OperationsStore(data_dir / "operations.sqlite3")
    mode = RuntimeModeStore(
        data_dir / "runtime-mode.json", default_mode=settings.app_mode
    ).load().mode

    nav_history = dashboard.history(limit=600)
    latest = nav_history[-1] if nav_history else None
    today = [item for item in nav_history if item.captured_at.astimezone(IST).date() == current.date()]
    day_start = today[0] if today else None

    recent = operations.recent_events(limit=500)
    relevant = [_safe_event(item) for item in recent if item.get("action") in _ALLOWED_ACTIONS]
    relevant = relevant[:80]

    decisions = [item for item in relevant if item["action"] == "FUND_DECISION"]
    orders = [item for item in relevant if item["action"] in {"ORDER_ACCEPTED", "PROTECTIVE_EXIT"}]
    errors = [
        item
        for item in relevant
        if item["action"]
        in {
            "RESEARCH_FAILED",
            "NEWS_REFRESH_FAILED",
            "ORDER_FAILED",
            "PROTECTIVE_EXIT_FAILED",
            "ZERODHA_UNAVAILABLE",
        }
    ]
    rejections = [item for item in relevant if item["action"] == "REJECTED"]
    scans = [item for item in relevant if item["action"] == "INTRADAY_OPPORTUNITY_SCAN"]

    heartbeat = Path(settings.heartbeat_path)
    heartbeat_age_seconds: float | None = None
    if heartbeat.exists():
        heartbeat_age_seconds = max(0.0, current.timestamp() - heartbeat.stat().st_mtime)

    total_value = latest.total_value if latest else settings.starting_cash
    pnl_total = total_value - settings.starting_cash
    pnl_today = total_value - day_start.total_value if day_start else 0.0

    return {
        "generated_at": current.isoformat(),
        "mode": mode.value,
        "market_phase": nse_capital_market_calendar(current).phase_at(current).value,
        "worker": {
            "heartbeat_age_seconds": round(heartbeat_age_seconds, 1)
            if heartbeat_age_seconds is not None
            else None,
            "healthy": heartbeat_age_seconds is not None and heartbeat_age_seconds <= 90,
        },
        "portfolio": {
            "cash": round(latest.cash, 2) if latest else settings.starting_cash,
            "deployed": round(latest.deployed, 2) if latest else 0.0,
            "holdings_value": round(latest.holdings_value, 2) if latest else 0.0,
            "total_value": round(total_value, 2),
            "pnl_total": round(pnl_total, 2),
            "pnl_total_pct": round((pnl_total / settings.starting_cash) * 100, 4),
            "pnl_today": round(pnl_today, 2),
        },
        "activity": {
            "recent_decisions": decisions[:12],
            "recent_orders": orders[:12],
            "recent_rejections": rejections[:12],
            "recent_errors": errors[:12],
            "latest_intraday_scan": scans[0] if scans else None,
        },
        "counts_in_recent_window": {
            "decisions": len(decisions),
            "orders": len(orders),
            "rejections": len(rejections),
            "errors": len(errors),
        },
    }
