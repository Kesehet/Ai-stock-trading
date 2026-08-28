# ruff: noqa: E501
from __future__ import annotations

import html
import json
from hmac import compare_digest
from http.server import ThreadingHTTPServer
from urllib.parse import urlparse

from app.config import Settings
from app.dashboard import render_dashboard
from app.dashboard_server import (
    DashboardServerHandler,
    _admin_tools,
    _write_html,
)
from app.fund_status import build_fund_status
from app.scheduler import IST
from app.zerodha_session import ZerodhaSession


def _write_json(handler: DashboardServerHandler, status: int, payload: object) -> None:
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _zerodha_status_card(
    *,
    configured: bool,
    session: ZerodhaSession | None,
    session_error: bool = False,
) -> str:
    if session_error:
        status = "ERROR"
        tone = "bad"
        note = "The saved Zerodha session could not be read. Reconnect to create a fresh session."
        action = "Reconnect Zerodha"
    elif not configured:
        status = "NOT CONFIGURED"
        tone = "bad"
        note = "Zerodha API credentials are missing. Save them in Connections, mode & export."
        action = "Open connection settings"
    elif session is None:
        status = "DISCONNECTED"
        tone = "warn"
        note = "API credentials are saved, but there is no active Zerodha login session."
        action = "Connect Zerodha"
    elif not session.is_valid():
        status = "SESSION EXPIRED"
        tone = "bad"
        expired_at = session.expires_at.astimezone(IST).strftime("%d %b, %I:%M %p IST")
        note = f"The Zerodha session expired at {expired_at}. Live market access is paused until renewal."
        action = "Renew Zerodha session"
    else:
        status = "CONNECTED"
        tone = "good"
        expires_at = session.expires_at.astimezone(IST).strftime("%d %b, %I:%M %p IST")
        note = f"Authenticated market session is active. Valid until {expires_at}."
        action = "Renew session"

    href = "#connections" if not configured else "/zerodha/login"
    return f"""
<style>
.zerodha-card{{margin:0 0 14px;display:grid;grid-template-columns:auto 1fr auto;gap:16px;align-items:center;background:linear-gradient(180deg,rgba(18,33,27,.97),rgba(10,22,17,.97));border:1px solid #20332a;border-radius:18px;padding:16px 18px;box-shadow:0 18px 50px rgba(0,0,0,.18)}}
.zerodha-brand{{font-size:13px;font-weight:800;letter-spacing:.08em;text-transform:uppercase;color:#dce9e2;white-space:nowrap}}
.zerodha-state strong{{display:block;font-size:17px;letter-spacing:.01em}}.zerodha-state small{{display:block;color:#8fa399;margin-top:4px;line-height:1.35}}
.zerodha-action{{border:1px solid #315244;background:#10271d;color:#c9f6df;border-radius:10px;padding:10px 13px;font-size:12px;font-weight:800;text-decoration:none;white-space:nowrap}}
.zerodha-action:hover{{background:#173729}}.zerodha-state .good{{color:#42d392}}.zerodha-state .warn{{color:#d6b45f}}.zerodha-state .bad{{color:#ff6b6b}}
@media(max-width:720px){{.zerodha-card{{grid-template-columns:1fr;gap:8px}}.zerodha-action{{text-align:center;margin-top:4px}}}}
</style>
<section class="zerodha-card" aria-label="Zerodha connection status">
<div class="zerodha-brand">Zerodha</div>
<div class="zerodha-state"><strong class="{tone}">{html.escape(status)}</strong><small>{html.escape(note)}</small></div>
<a class="zerodha-action" href="{href}">{html.escape(action)}</a>
</section>
"""


class DashboardServerV2Handler(DashboardServerHandler):
    def _connection_card(self) -> str:
        configured = self._credentials() is not None
        try:
            session = self.session_store.load()
            session_error = False
        except (OSError, ValueError, KeyError, TypeError):
            session = None
            session_error = True
        return _zerodha_status_card(
            configured=configured,
            session=session,
            session_error=session_error,
        )

    def _telemetry_authorized(self) -> bool:
        expected = self.settings.dashboard_admin_token.get_secret_value().strip()
        if not expected:
            return False
        supplied = self.headers.get("Authorization", "")
        prefix = "Bearer "
        if not supplied.startswith(prefix):
            return False
        return compare_digest(supplied[len(prefix) :].strip(), expected)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/fund-status.json":
            if not self._telemetry_authorized():
                _write_json(self, 401, {"error": "unauthorized"})
                return
            _write_json(self, 200, build_fund_status(self.settings))
            return
        if path != "/":
            super().do_GET()
            return

        page = render_dashboard(self.settings)
        connection_card = self._connection_card()
        controls = _admin_tools(
            zerodha_configured=self._credentials() is not None,
            session_valid=self._session_valid(),
            ollama_configured=self._ollama_configured(),
            admin_enabled=bool(self.settings.dashboard_admin_token.get_secret_value()),
            mode=self.mode_store.load().mode,
        ).replace('<details class="admin-tools">', '<details id="connections" class="admin-tools">', 1)
        page = page.replace("</header>", f"</header>{connection_card}", 1)
        _write_html(self, 200, page.replace("</main>", f"{controls}</main>", 1))


def main() -> None:
    settings = Settings()
    DashboardServerV2Handler.settings = settings
    ThreadingHTTPServer(
        (settings.dashboard_bind_host, settings.dashboard_port),
        DashboardServerV2Handler,
    ).serve_forever()


if __name__ == "__main__":
    main()
