# ruff: noqa: E501
from __future__ import annotations

import html
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from app.config import AppMode, Settings
from app.dashboard_store import DashboardSnapshotStore, PortfolioSnapshot
from app.live_order_ledger import LiveOrderLedger
from app.persistent_paper import PersistentPaperBroker
from app.runtime_mode import RuntimeModeStore


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
    updated = latest.captured_at.astimezone().strftime("%d %b %Y, %I:%M %p")
    pnl_class = "positive" if pnl >= 0 else "negative"

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
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
.positive {{ color:var(--green); }} .negative {{ color:var(--red); }}
.chart-grid {{ margin-top:14px; display:grid; grid-template-columns:minmax(0,2fr) minmax(280px,1fr); gap:14px; }}
.chart-card {{ min-height:290px; }}
.chart-title {{ display:flex; justify-content:space-between; align-items:center; margin-bottom:18px; }}
.chart-title strong {{ font-size:16px; }}
.chart-title span {{ color:var(--muted); font-size:12px; }}
.spark {{ color:var(--green); width:100%; margin-top:16px; }} .spark svg {{ width:100%; height:180px; overflow:visible; }}
.baseline {{ border-top:1px dashed var(--line); margin-top:-15px; }}
.allocation-row {{ margin:16px 0; }} .allocation-label {{ display:flex; justify-content:space-between; gap:14px; font-size:13px; margin-bottom:7px; }}
.bar {{ height:7px; border-radius:999px; background:#16281f; overflow:hidden; }} .bar i {{ display:block; height:100%; border-radius:inherit; background:linear-gradient(90deg,var(--gold),var(--green)); }}
.footerline {{ margin-top:14px; display:flex; justify-content:space-between; gap:14px; color:var(--muted); font-size:12px; }}
.empty {{ color:var(--muted); padding:24px 0; }}
@media(max-width:820px) {{ .grid {{ grid-template-columns:repeat(2,1fr); }} .chart-grid {{ grid-template-columns:1fr; }} }}
@media(max-width:520px) {{ main {{ width:min(100% - 20px,1180px); padding-top:22px; }} header {{ align-items:flex-start; }} .grid {{ grid-template-columns:1fr; }} .value {{ font-size:27px; }} }}
</style>
</head>
<body>
<main>
<header>
<div><h1>AI Stock Fund</h1><div class="sub">Portfolio result. Nothing else.</div></div>
<div class="mode {mode_class}">{mode} MODE</div>
</header>
<section class="grid">
<div class="card"><div class="label">Starting capital</div><div class="value">{_money(starting)}</div><div class="small">Capital allocated to this fund</div></div>
<div class="card"><div class="label">Capital deployed</div><div class="value">{_money(latest.deployed)}</div><div class="small">Money currently in bot-managed positions</div></div>
<div class="card"><div class="label">Current value</div><div class="value">{_money(latest.total_value)}</div><div class="small">Cash + marked holdings</div></div>
<div class="card"><div class="label">Total P&amp;L</div><div class="value {pnl_class}">{_money(pnl)}</div><div class="small {pnl_class}">{_pct(pnl_pct)} since start</div></div>
</section>
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
