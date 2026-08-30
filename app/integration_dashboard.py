from __future__ import annotations

import html

from app.integration_health import IntegrationCheck


def _status_label(status: str) -> str:
    return {
        "connected": "Connected",
        "degraded": "Degraded",
        "failed": "Failed",
        "not_configured": "Not configured",
        "ready": "Ready to test",
    }.get(status, status.replace("_", " ").title())


def render_integrations_page(
    configured: dict[str, bool],
    checks: list[IntegrationCheck] | None,
    *,
    admin_enabled: bool,
) -> str:
    tested = {item.key: item for item in checks or []}
    services = [
        ("zerodha", "Zerodha Kite Connect", "Market data and order execution", True),
        ("ollama", "Ollama Cloud", "AI research and structured decisions", True),
        ("google_news", "Google News RSS", "Company-news evidence ingestion", False),
        ("nse_archives", "NSE Archives", "Official bhavcopy history fallback", False),
    ]
    cards: list[str] = []
    for key, name, purpose, needs_config in services:
        result = tested.get(key)
        if result is not None:
            status = result.status
            detail = result.detail
            latency = f" · {result.latency_ms} ms" if result.latency_ms is not None else ""
        elif needs_config and not configured.get(key, False):
            status = "not_configured"
            detail = "Configuration is incomplete."
            latency = ""
        else:
            status = "ready"
            detail = "No live check has been run on this page yet."
            latency = ""
        cards.append(
            f"""
<section class="card status-{html.escape(status)}">
<div class="card-head"><div><h2>{html.escape(name)}</h2><p>{html.escape(purpose)}</p></div><span class="badge">{html.escape(_status_label(status))}</span></div>
<p class="detail">{html.escape(detail)}{html.escape(latency)}</p>
<button type="submit" name="integration" value="{html.escape(key)}">Test {html.escape(name)}</button>
</section>
"""
        )

    disabled_note = "" if admin_enabled else "<p class=\"warning\">Testing is disabled until DASHBOARD_ADMIN_TOKEN is configured.</p>"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Integration health</title><style>
:root{{color-scheme:dark}}*{{box-sizing:border-box}}body{{margin:0;background:#07110d;color:#f3f7f4;font-family:system-ui,-apple-system,Segoe UI,sans-serif}}main{{width:min(1050px,calc(100% - 32px));margin:34px auto 60px}}a{{color:#42d392;text-decoration:none}}h1{{font-size:30px;margin:8px 0}}.lead{{color:#9fb3a9;max-width:760px;line-height:1.55}}.top{{display:flex;align-items:center;justify-content:space-between;gap:16px}}.grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;margin-top:22px}}.card{{background:#0c1813;border:1px solid #20332a;border-radius:16px;padding:18px}}.card-head{{display:flex;justify-content:space-between;gap:14px;align-items:flex-start}}h2{{font-size:18px;margin:0 0 4px}}.card p{{margin:0;color:#91a59a;font-size:13px}}.detail{{padding:14px 0!important;min-height:58px;line-height:1.45}}.badge{{white-space:nowrap;border-radius:999px;padding:6px 9px;font-size:11px;font-weight:800;background:#1a2b23;color:#c9d9d1}}.status-connected{{border-color:#285f48}}.status-connected .badge{{background:#123b2b;color:#9ff0c5}}.status-degraded{{border-color:#6a5928}}.status-degraded .badge{{background:#3b3215;color:#f3d77c}}.status-failed{{border-color:#6b3030}}.status-failed .badge{{background:#3b1717;color:#ffaaaa}}.status-not_configured{{border-color:#4a4e52}}button{{border:1px solid #315244;background:#10271d;color:#c9f6df;border-radius:10px;padding:10px 12px;font-weight:750;cursor:pointer}}form.controls{{margin-top:18px;background:#0c1813;border:1px solid #20332a;border-radius:16px;padding:16px;display:flex;gap:10px;align-items:center;flex-wrap:wrap}}input{{min-width:260px;flex:1;background:#08130f;color:#f3f7f4;border:1px solid #294238;border-radius:10px;padding:10px 12px}}.all{{background:#173728}}.warning{{color:#f0c57a!important}}.note{{font-size:12px;color:#7f9489;margin-top:16px;line-height:1.5}}@media(max-width:720px){{.grid{{grid-template-columns:1fr}}.top{{align-items:flex-start;flex-direction:column}}}}
</style></head><body><main>
<div class="top"><div><a href="/">← Dashboard</a><h1>Integrations &amp; Connection Health</h1><p class="lead">Run an actual API/network check against every third-party service the trading runtime depends on. Tests never display saved secrets.</p></div></div>
{disabled_note}
<form class="controls" method="post" action="/admin">
<input type="password" name="admin_token" autocomplete="current-password" placeholder="Admin password" required {'disabled' if not admin_enabled else ''}>
<input type="hidden" name="action" value="test_integrations">
<button class="all" type="submit" name="integration" value="all" {'disabled' if not admin_enabled else ''}>Test all integrations</button>
<div class="grid">{''.join(cards)}</div>
</form>
<p class="note">Zerodha and Ollama checks validate authentication. Google News validates the RSS source used for company research. NSE Archives validates access to a recent official bhavcopy without downloading the complete archive. Hostinger is intentionally not shown here because its API key is held by deployment automation, not by the running trading service.</p>
</main></body></html>"""
