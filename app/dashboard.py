# ruff: noqa: E501
from __future__ import annotations

import html
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from time import time
from typing import Any
from urllib.parse import urlparse

from app.config import AppMode, Settings
from app.dashboard_store import DashboardSnapshotStore, PortfolioSnapshot
from app.live_order_ledger import LiveOrderLedger
from app.operations import OperationsStore
from app.persistent_paper import PersistentPaperBroker
from app.runtime_mode import RuntimeModeStore
from app.scheduler import IST


def _money(value: float) -> str:
    sign = "-" if value < 0 else ""
    return f"{sign}₹{abs(value):,.0f}"


def _pct(value: float) -> str:
    return f"{value:+.2f}%"


def _active_mode(settings: Settings) -> AppMode:
    return RuntimeModeStore(
        Path(settings.data_dir) / "runtime-mode.json",
        default_mode=settings.app_mode,
    ).load().mode


def _sparkline(values: list[float], width: int = 760, height: int = 170) -> str:
    if not values:
        values = [0.0, 0.0]
    if len(values) == 1:
        values = [values[0], values[0]]
    low = min(values)
    high = max(values)
    span = high - low or 1.0
    points = []
    for index, value in enumerate(values):
        x = 12 + (index / (len(values) - 1)) * (width - 24)
        y = 12 + ((high - value) / span) * (height - 24)
        points.append(f"{x:.1f},{y:.1f}")
    return (
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Portfolio value trend">'
        f'<polyline points="{" ".join(points)}" fill="none" stroke="currentColor" '
        'stroke-width="3" stroke-linecap="round" stroke-linejoin="round" />'
        "</svg>"
    )


def _paper_fallback(settings: Settings) -> tuple[PortfolioSnapshot, list[tuple[str, float]]]:
    broker = PersistentPaperBroker(
        Path(settings.data_dir) / "paper.sqlite3",
        starting_cash=settings.starting_cash,
    )
    positions = broker.get_positions()
    cash = broker.get_cash()
    deployed = sum(position.quantity * position.average_price for position in positions)
    snapshot = PortfolioSnapshot(
        captured_at=datetime.now(UTC),
        cash=cash,
        deployed=deployed,
        holdings_value=deployed,
        total_value=cash + deployed,
    )
    allocations = [
        (position.symbol, position.quantity * position.average_price) for position in positions
    ]
    return snapshot, allocations


def _live_fallback(settings: Settings) -> tuple[PortfolioSnapshot, list[tuple[str, float]]]:
    ledger = LiveOrderLedger(Path(settings.data_dir) / "live-orders.sqlite3")
    positions = ledger.managed_positions()
    cash = ledger.managed_cash(settings.starting_cash)
    deployed = sum(position.quantity * position.average_price for position in positions)
    snapshot = PortfolioSnapshot(
        captured_at=datetime.now(UTC),
        cash=cash,
        deployed=deployed,
        holdings_value=deployed,
        total_value=cash + deployed,
    )
    allocations = [
        (position.symbol, position.quantity * position.average_price) for position in positions
    ]
    return snapshot, allocations


def _dashboard_data(
    settings: Settings,
    mode: AppMode,
) -> tuple[PortfolioSnapshot, list[PortfolioSnapshot], list[tuple[str, float]], bool]:
    store = DashboardSnapshotStore(Path(settings.data_dir) / "dashboard.sqlite3")
    latest = store.latest()
    history = store.history()
    is_marked = latest is not None
    if mode == AppMode.LIVE:
        fallback, allocations = _live_fallback(settings)
    else:
        fallback, allocations = _paper_fallback(settings)
    if latest is None:
        latest = fallback
        history = [fallback]
    return latest, history, allocations, is_marked


def _heartbeat(settings: Settings) -> tuple[str, str, str]:
    path = Path(settings.heartbeat_path)
    try:
        stamp = float(path.read_text(encoding="utf-8").strip())
        age = max(0, int(time() - stamp))
    except (OSError, ValueError):
        return "OFFLINE", "No heartbeat file", "bad"
    if age <= 20:
        return "RUNNING", f"Heartbeat {age}s ago", "good"
    if age <= 90:
        return "BUSY", f"Heartbeat {age}s ago", "warn"
    return "STALE", f"Heartbeat {age}s ago", "bad"


def _event_time(raw: str) -> str:
    try:
        value = datetime.fromisoformat(raw)
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(IST).strftime("%I:%M:%S %p")
    except ValueError:
        return raw


def _event_summary(event: dict[str, Any]) -> tuple[str, str, str]:
    action = str(event.get("action", "EVENT"))
    payload = event.get("payload") or {}
    symbol = str(payload.get("symbol", ""))
    tone = "neutral"

    if action == "FUND_DECISION":
        decision = str(payload.get("action", "HOLD"))
        confidence = payload.get("confidence")
        conf = f" · {float(confidence) * 100:.0f}% confidence" if isinstance(confidence, (int, float)) else ""
        text = f"{symbol} — AI decided {decision}{conf}"
        tone = "good" if decision == "BUY" else "bad" if decision == "SELL" else "neutral"
    elif action == "RESEARCH_FAILED":
        text = f"{symbol} — AI research failed ({payload.get('error', 'unknown')})"
        tone = "bad"
    elif action == "NEWS_REFRESHED":
        text = f"{symbol} — news/evidence refreshed"
    elif action == "APPROVED":
        text = f"{symbol} — risk engine approved trade"
        tone = "good"
    elif action == "REJECTED":
        text = f"{symbol} — risk rejected trade: {payload.get('reason', 'rule failed')}"
        tone = "warn"
    elif action == "ORDER_ACCEPTED":
        side = payload.get("side", "ORDER")
        qty = payload.get("quantity", "?")
        price = payload.get("average_price")
        price_text = f" @ ₹{float(price):,.2f}" if isinstance(price, (int, float)) else ""
        text = f"{symbol} — PAPER {side} {qty}{price_text}"
        tone = "good"
    elif action == "DYNAMIC_NSE_UNIVERSE_WARMED":
        eligible = payload.get("eligible_symbols", "?")
        text = f"NSE universe ready — {eligible} eligible symbols"
        tone = "good"
    elif action == "PHASE_CHANGED":
        text = f"Market phase changed to {str(payload.get('phase', '?')).upper()}"
    elif action == "MODE_ACTIVE":
        text = f"Trader running in {str(payload.get('mode', '?')).upper()} mode"
        tone = "good"
    elif action == "ZERODHA_UNAVAILABLE":
        text = f"Zerodha unavailable — {payload.get('reason', 'unknown reason')}"
        tone = "bad"
    elif action == "STARTED":
        text = "Autonomous runtime started"
        tone = "good"
    elif action == "TICK_FAILED":
        text = "Trading cycle failed — check diagnostics"
        tone = "bad"
    else:
        pretty = action.replace("_", " ").title()
        text = f"{symbol + ' — ' if symbol else ''}{pretty}"
    return text, tone, action


def _operations_panel(settings: Settings) -> tuple[str, str, str, str, str]:
    store = OperationsStore(Path(settings.data_dir) / "operations.sqlite3")
    events = store.recent_events(80)
    heartbeat_label, heartbeat_note, heartbeat_tone = _heartbeat(settings)

    market_phase = "UNKNOWN"
    universe_label = "Dynamic NSE" if settings.dynamic_universe else "Watchlist"
    universe_note = "Waiting for universe scan"
    shortlist: list[str] = []

    for event in events:
        action = event.get("action")
        payload = event.get("payload") or {}
        if action == "PHASE_CHANGED" and market_phase == "UNKNOWN":
            market_phase = str(payload.get("phase", "unknown")).upper()
        if action == "DYNAMIC_NSE_UNIVERSE_WARMED" and not shortlist:
            raw_shortlist = payload.get("shortlist") or []
            shortlist = [str(item) for item in raw_shortlist[: settings.max_ai_candidates]]
            universe_note = f"{payload.get('eligible_symbols', '?')} eligible · top {len(shortlist)} sent to AI"

    useful_actions = {
        "STARTED", "MODE_ACTIVE", "PHASE_CHANGED", "DYNAMIC_NSE_UNIVERSE_WARMED",
        "FUND_DECISION", "RESEARCH_FAILED", "APPROVED", "REJECTED",
        "ORDER_ACCEPTED", "ORDER_FAILED", "PROTECTIVE_EXIT", "TICK_FAILED",
        "ZERODHA_UNAVAILABLE", "NEWS_REFRESH_FAILED",
    }
    useful = [event for event in events if event.get("action") in useful_actions][:18]
    rows: list[str] = []
    for event in useful:
        text, tone, action = _event_summary(event)
        rows.append(
            '<div class="activity-row">'
            f'<time>{html.escape(_event_time(str(event.get("created_at", ""))))}</time>'
            f'<span class="activity-dot {tone}"></span>'
            f'<div><strong>{html.escape(text)}</strong><small>{html.escape(action)}</small></div>'
            '</div>'
        )
    if not rows:
        rows.append('<div class="empty">No trading activity recorded yet.</div>')

    chips = "".join(f'<span class="chip">{html.escape(symbol)}</span>' for symbol in shortlist)
    if not chips:
        chips = '<span class="muted">Waiting for first shortlist…</span>'

    return (
        heartbeat_label,
        heartbeat_note,
        heartbeat_tone,
        market_phase,
        f"""<div class="ops-card card">
<div class="chart-title"><strong>Live autonomous operations</strong><span>Auto-refreshes every 10 seconds</span></div>
<div class="ops-grid">
<div class="op-stat"><div class="label">Worker</div><div class="op-value {heartbeat_tone}">{heartbeat_label}</div><div class="small">{html.escape(heartbeat_note)}</div></div>
<div class="op-stat"><div class="label">Market</div><div class="op-value">{html.escape(market_phase)}</div><div class="small">NSE capital market phase</div></div>
<div class="op-stat"><div class="label">Universe</div><div class="op-value">{html.escape(universe_label)}</div><div class="small">{html.escape(universe_note)}</div></div>
<div class="op-stat"><div class="label">Decision cadence</div><div class="op-value">{settings.decision_interval_seconds // 60} min</div><div class="small">Per-symbol AI review interval</div></div>
</div>
<div class="shortlist"><div class="label">Current AI shortlist</div><div class="chips">{chips}</div></div>
<div class="activity"><div class="label">Recent fund activity</div>{''.join(rows)}</div>
</div>""",
    )


def render_dashboard(settings: Settings) -> str:
    active_mode = _active_mode(settings)
    latest, history, allocations, is_marked = _dashboard_data(settings, active_mode)
    starting = settings.starting_cash
    pnl = latest.total_value - starting
    pnl_pct = (pnl / starting * 100) if starting else 0.0
    mode = "REAL" if active_mode == AppMode.LIVE else "PAPER"
    mode_class = "real" if mode == "REAL" else "paper"
    values = [item.total_value for item in history]
    chart = _sparkline(values)
    allocation_total = sum(value for _, value in allocations) or 1.0
    allocation_rows = "".join(
        (
            '<div class="allocation-row">'
            f'<div class="allocation-label"><span>{html.escape(symbol)}</span>'
            f'<span>{_money(value)}</span></div>'
            f'<div class="bar"><i style="width:{min(100.0, value / allocation_total * 100):.2f}%"></i></div>'
            "</div>"
        )
        for symbol, value in sorted(allocations, key=lambda item: item[1], reverse=True)[:6]
    )
    if not allocation_rows:
        allocation_rows = '<div class="empty">No open positions yet.</div>'

    marked_note = (
        "Marked using the latest real market valuation snapshot."
        if is_marked
        else "No market mark yet; open positions are temporarily shown at cost basis."
    )
    updated = latest.captured_at.astimezone(IST).strftime("%d %b %Y, %I:%M %p IST")
    pnl_class = "positive" if pnl >= 0 else "negative"
    _, _, _, _, operations_html = _operations_panel(settings)

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="10">
<title>AI Stock Fund</title>
<style>
:root {{ color-scheme: dark; --bg:#07110d; --panel:#0c1813; --panel2:#101f19; --text:#f3f7f4; --muted:#8fa399; --line:#20332a; --green:#42d392; --red:#ff6b6b; --gold:#d6b45f; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:radial-gradient(circle at top right,#123525 0,#07110d 38%); color:var(--text); font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; min-height:100vh; }}
main {{ width:min(1180px,calc(100% - 32px)); margin:0 auto; padding:38px 0 56px; }}
header {{ display:flex; align-items:flex-end; justify-content:space-between; gap:18px; margin-bottom:26px; }}
h1 {{ margin:0; font-size:28px; letter-spacing:-.04em; }}
.sub {{ color:var(--muted); margin-top:7px; font-size:14px; }}
.mode {{ padding:8px 12px; border-radius:999px; font-size:12px; font-weight:800; letter-spacing:.12em; border:1px solid var(--line); }}
.mode.paper {{ color:#b6f5d6; background:#0f2a1d; }} .mode.real {{ color:#ffd0d0; background:#351717; }}
.grid {{ display:grid; grid-template-columns:repeat(4,1fr); gap:14px; }}
.card {{ background:linear-gradient(180deg,rgba(18,33,27,.95),rgba(10,22,17,.95)); border:1px solid var(--line); border-radius:18px; padding:20px; box-shadow:0 18px 50px rgba(0,0,0,.18); }}
.label {{ color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.11em; }}
.value {{ margin-top:11px; font-size:30px; font-weight:760; letter-spacing:-.04em; }}
.small {{ margin-top:7px; color:var(--muted); font-size:13px; }}
.positive,.good {{ color:var(--green); }} .negative,.bad {{ color:var(--red); }} .warn {{ color:var(--gold); }} .muted {{ color:var(--muted); }}
.chart-grid {{ margin-top:14px; display:grid; grid-template-columns:minmax(0,2fr) minmax(280px,1fr); gap:14px; }}
.chart-card {{ min-height:290px; }}
.chart-title {{ display:flex; justify-content:space-between; align-items:center; gap:12px; margin-bottom:18px; }}
.chart-title strong {{ font-size:16px; }} .chart-title span {{ color:var(--muted); font-size:12px; }}
.spark {{ color:var(--green); width:100%; margin-top:16px; }} .spark svg {{ width:100%; height:180px; overflow:visible; }}
.baseline {{ border-top:1px dashed var(--line); margin-top:-15px; }}
.allocation-row {{ margin:16px 0; }} .allocation-label {{ display:flex; justify-content:space-between; gap:14px; font-size:13px; margin-bottom:7px; }}
.bar {{ height:7px; border-radius:999px; background:#16281f; overflow:hidden; }} .bar i {{ display:block; height:100%; border-radius:inherit; background:linear-gradient(90deg,var(--gold),var(--green)); }}
.footerline {{ margin-top:14px; display:flex; justify-content:space-between; gap:14px; color:var(--muted); font-size:12px; }}
.empty {{ color:var(--muted); padding:24px 0; }}
.ops-card {{ margin-top:14px; }} .ops-grid {{ display:grid; grid-template-columns:repeat(4,1fr); gap:10px; }}
.op-stat {{ padding:14px; border:1px solid var(--line); border-radius:14px; background:#091610; }} .op-value {{ font-size:20px; font-weight:800; margin-top:8px; }}
.shortlist {{ margin-top:18px; padding-top:16px; border-top:1px solid var(--line); }} .chips {{ display:flex; gap:8px; flex-wrap:wrap; margin-top:10px; }}
.chip {{ padding:7px 10px; border:1px solid #315244; border-radius:999px; background:#0d2419; color:#c9f6df; font-size:12px; font-weight:750; }}
.activity {{ margin-top:18px; }} .activity>.label {{ margin-bottom:8px; }}
.activity-row {{ display:grid; grid-template-columns:90px 10px 1fr; gap:10px; align-items:start; padding:10px 0; border-top:1px solid rgba(32,51,42,.6); }}
.activity-row time {{ color:var(--muted); font-size:11px; padding-top:2px; }} .activity-row strong {{ display:block; font-size:13px; font-weight:650; }} .activity-row small {{ display:block; color:var(--muted); font-size:10px; margin-top:3px; }}
.activity-dot {{ width:8px; height:8px; border-radius:50%; margin-top:5px; background:#708279; }} .activity-dot.good {{ background:var(--green); }} .activity-dot.bad {{ background:var(--red); }} .activity-dot.warn {{ background:var(--gold); }}
@media(max-width:820px) {{ .grid,.ops-grid {{ grid-template-columns:repeat(2,1fr); }} .chart-grid {{ grid-template-columns:1fr; }} }}
@media(max-width:520px) {{ main {{ width:min(100% - 20px,1180px); padding-top:22px; }} header {{ align-items:flex-start; }} .grid,.ops-grid {{ grid-template-columns:1fr; }} .value {{ font-size:27px; }} .activity-row {{ grid-template-columns:72px 8px 1fr; }} }}
</style>
</head>
<body>
<main>
<header>
<div><h1>AI Stock Fund</h1><div class="sub">Autonomous fund operations + portfolio results.</div></div>
<div class="mode {mode_class}">{mode} MODE</div>
</header>
<section class="grid">
<div class="card"><div class="label">Starting capital</div><div class="value">{_money(starting)}</div><div class="small">Capital allocated to this fund</div></div>
<div class="card"><div class="label">Capital deployed</div><div class="value">{_money(latest.deployed)}</div><div class="small">Money currently in bot-managed positions</div></div>
<div class="card"><div class="label">Current value</div><div class="value">{_money(latest.total_value)}</div><div class="small">Cash + marked holdings</div></div>
<div class="card"><div class="label">Total P&amp;L</div><div class="value {pnl_class}">{_money(pnl)}</div><div class="small {pnl_class}">{_pct(pnl_pct)} since start</div></div>
</section>
{operations_html}
<section class="chart-grid">
<div class="card chart-card">
<div class="chart-title"><strong>Portfolio value</strong><span>{len(history)} snapshots</span></div>
<div class="spark">{chart}</div><div class="baseline"></div>
<div class="footerline"><span>Cash: {_money(latest.cash)}</span><span>Updated {updated}</span></div>
</div>
<div class="card chart-card">
<div class="chart-title"><strong>Where the money is</strong><span>Bot-managed positions</span></div>
{allocation_rows}
<div class="footerline"><span>{html.escape(marked_note)}</span></div>
</div>
</section>
</main>
</body>
</html>"""


class DashboardHandler(BaseHTTPRequestHandler):
    settings = Settings()

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/healthz":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"ok")
            return
        if path != "/":
            self.send_error(404)
            return
        content = render_dashboard(self.settings).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; style-src 'unsafe-inline'; img-src 'self'; "
            "base-uri 'none'; frame-ancestors 'none'",
        )
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    settings = Settings()
    DashboardHandler.settings = settings
    server = ThreadingHTTPServer(
        (settings.dashboard_bind_host, settings.dashboard_port),
        DashboardHandler,
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
