# ruff: noqa: E501,I001
from __future__ import annotations

import hmac
import html
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from app.config import AppMode, Settings
from app.dashboard import render_dashboard
from app.diagnostic_export import build_diagnostic_export
from app.live_order_ledger import LiveOrderLedger
from app.ollama_credentials import OllamaCredentialStore, OllamaCredentials
from app.operations import OperationsStore
from app.runtime_mode import RuntimeModeStore
from app.zerodha_credentials import ZerodhaCredentialStore, ZerodhaCredentials
from app.zerodha_session import ZerodhaAuthClient, ZerodhaSessionStore


def _write_html(handler: BaseHTTPRequestHandler, status: int, body: str) -> None:
    content = body.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("X-Frame-Options", "DENY")
    handler.send_header("Referrer-Policy", "no-referrer")
    handler.send_header(
        "Content-Security-Policy",
        "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; "
        "form-action 'self' https://kite.zerodha.com; base-uri 'none'; frame-ancestors 'none'",
    )
    handler.send_header("Content-Length", str(len(content)))
    handler.end_headers()
    handler.wfile.write(content)


def _message_page(title: str, message: str, extra: str = "") -> str:
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title><style>
body{{margin:0;background:#07110d;color:#f3f7f4;font-family:system-ui,-apple-system,Segoe UI,sans-serif;display:grid;place-items:center;min-height:100vh}}
main{{width:min(620px,calc(100% - 32px));background:#0c1813;border:1px solid #20332a;border-radius:18px;padding:28px}}
h1{{margin:0 0 12px;font-size:24px}}p{{color:#a8bbb1;line-height:1.6}}a{{color:#42d392}}
</style></head><body><main><h1>{html.escape(title)}</h1><p>{html.escape(message)}</p>{extra}<p><a href="/">Back to dashboard</a></p></main></body></html>"""


def _admin_tools(
    zerodha_configured: bool,
    session_valid: bool,
    ollama_configured: bool,
    admin_enabled: bool,
    mode: AppMode,
) -> str:
    status = (
        f"Zerodha: {'configured' if zerodha_configured else 'not configured'} · "
        f"Session: {'connected' if session_valid else 'not connected'} · "
        f"Ollama Cloud: {'configured' if ollama_configured else 'not configured'} · "
        f"Mode: {'REAL' if mode == AppMode.LIVE else 'PAPER'}"
    )
    if not admin_enabled:
        status += " · admin setup disabled until DASHBOARD_ADMIN_TOKEN is configured"
    next_mode = AppMode.PAPER if mode == AppMode.LIVE else AppMode.LIVE
    switch_label = "Switch to PAPER" if next_mode == AppMode.PAPER else "Switch to REAL MONEY"
    switch_class = "danger" if next_mode == AppMode.LIVE else ""
    return f"""
<style>
.admin-tools{{margin-top:14px;background:rgba(10,22,17,.78);border:1px solid #20332a;border-radius:16px;padding:16px 18px;color:#8fa399}}
.admin-tools summary{{cursor:pointer;color:#dce9e2;font-weight:700;list-style:none}}
.admin-tools form{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin-top:14px}}
.admin-tools input{{width:100%;background:#08130f;color:#f3f7f4;border:1px solid #294238;border-radius:10px;padding:10px 12px}}
.admin-tools button,.admin-tools a.button{{border:1px solid #315244;background:#10271d;color:#c9f6df;border-radius:10px;padding:10px 12px;font-weight:700;cursor:pointer;text-decoration:none;text-align:center}}
.admin-tools button.danger{{border-color:#6b3030;background:#351717;color:#ffd0d0}}
.admin-note{{font-size:12px;margin-top:8px}}.wide{{grid-column:1/-1}}
@media(max-width:720px){{.admin-tools form{{grid-template-columns:1fr}}.wide{{grid-column:auto}}}}
</style>
<details class="admin-tools">
<summary>Connections, mode &amp; export</summary>
<div class="admin-note">{html.escape(status)}. Secrets are write-only and never included in exports.</div>
<form method="post" action="/admin">
<input class="wide" type="password" name="admin_token" autocomplete="current-password" placeholder="Admin password" required>
<input type="text" name="zerodha_api_key" autocomplete="off" placeholder="Zerodha API key">
<input type="password" name="zerodha_api_secret" autocomplete="new-password" placeholder="Zerodha API secret">
<button type="submit" name="action" value="save_zerodha">Save Zerodha</button>
<input type="url" name="ollama_base_url" value="https://ollama.com" autocomplete="off" placeholder="Ollama Cloud URL">
<input type="text" name="ollama_model" value="gpt-oss:120b" autocomplete="off" placeholder="Ollama model">
<input type="password" name="ollama_api_key" autocomplete="new-password" placeholder="Ollama API key">
<button type="submit" name="action" value="save_ollama">Save Ollama Cloud</button>
<button type="submit" name="action" value="export">Export trading diagnostic</button>
<a class="button" href="/zerodha/login">Connect / renew Zerodha</a>
<input type="hidden" name="desired_mode" value="{next_mode.value}">
<button class="wide {switch_class}" type="submit" name="action" value="switch_mode">{switch_label}</button>
</form>
</details>
"""


class DashboardServerHandler(BaseHTTPRequestHandler):
    settings = Settings()

    @property
    def data_dir(self) -> Path:
        return Path(self.settings.data_dir)

    @property
    def credential_store(self) -> ZerodhaCredentialStore:
        return ZerodhaCredentialStore(self.data_dir / "zerodha-credentials.json")

    @property
    def ollama_store(self) -> OllamaCredentialStore:
        return OllamaCredentialStore(self.data_dir / "ollama-credentials.json")

    @property
    def session_store(self) -> ZerodhaSessionStore:
        return ZerodhaSessionStore(self.data_dir / "zerodha-session.json")

    @property
    def mode_store(self) -> RuntimeModeStore:
        return RuntimeModeStore(
            self.data_dir / "runtime-mode.json",
            default_mode=self.settings.app_mode,
        )

    @property
    def operations(self) -> OperationsStore:
        return OperationsStore(self.data_dir / "operations.sqlite3")

    def _credentials(self) -> ZerodhaCredentials | None:
        api_key = self.settings.zerodha_api_key.strip()
        api_secret = self.settings.zerodha_api_secret.get_secret_value().strip()
        if api_key and api_secret:
            return ZerodhaCredentials(api_key=api_key, api_secret=api_secret)
        return self.credential_store.load()

    def _ollama_configured(self) -> bool:
        return bool(self.settings.ollama_api_key.get_secret_value().strip()) or self.ollama_store.load() is not None

    def _session_valid(self) -> bool:
        session = self.session_store.load()
        return session is not None and session.is_valid()

    def _admin_authorized(self, supplied: str) -> bool:
        expected = self.settings.dashboard_admin_token.get_secret_value()
        return bool(expected) and hmac.compare_digest(supplied, expected)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/healthz":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"ok")
            return
        if path == "/zerodha/callback":
            self._handle_zerodha_callback(parsed.query)
            return
        if path == "/zerodha/login":
            credentials = self._credentials()
            if credentials is None:
                _write_html(self, 503, _message_page("Zerodha not configured", "Save the API key and secret first."))
                return
            self.send_response(302)
            self.send_header("Location", ZerodhaAuthClient(credentials.api_key, credentials.api_secret).login_url())
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return
        if path != "/":
            self.send_error(404)
            return
        page = render_dashboard(self.settings)
        controls = _admin_tools(
            zerodha_configured=self._credentials() is not None,
            session_valid=self._session_valid(),
            ollama_configured=self._ollama_configured(),
            admin_enabled=bool(self.settings.dashboard_admin_token.get_secret_value()),
            mode=self.mode_store.load().mode,
        )
        _write_html(self, 200, page.replace("</main>", f"{controls}</main>"))

    def do_POST(self) -> None:  # noqa: N802
        if urlparse(self.path).path != "/admin":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_error(400)
            return
        if length <= 0 or length > 16_384:
            self.send_error(413)
            return
        params = parse_qs(self.rfile.read(length).decode("utf-8"), keep_blank_values=True)
        admin_token = params.get("admin_token", [""])[0]
        if not self.settings.dashboard_admin_token.get_secret_value():
            _write_html(self, 503, _message_page("Admin setup disabled", "Configure DASHBOARD_ADMIN_TOKEN and redeploy once."))
            return
        if not self._admin_authorized(admin_token):
            _write_html(self, 403, _message_page("Access denied", "The dashboard admin password is incorrect."))
            return
        action = params.get("action", [""])[0]
        if action == "save_zerodha":
            self._save_zerodha(params)
            return
        if action == "save_ollama":
            self._save_ollama(params)
            return
        if action == "switch_mode":
            self._switch_mode(params)
            return
        if action == "export":
            self._export_diagnostic()
            return
        self.send_error(400)

    def _save_zerodha(self, params: dict[str, list[str]]) -> None:
        api_key = params.get("zerodha_api_key", [""])[0].strip()
        api_secret = params.get("zerodha_api_secret", [""])[0].strip()
        try:
            self.credential_store.save(ZerodhaCredentials(api_key=api_key, api_secret=api_secret))
            self.session_store.clear()
            self.operations.append_event(
                "broker", "ZERODHA_CREDENTIALS_UPDATED", {"api_key_suffix": api_key[-4:] if len(api_key) >= 4 else "****"}
            )
        except ValueError as exc:
            _write_html(self, 400, _message_page("Invalid Zerodha credentials", str(exc)))
            return
        _write_html(self, 200, _message_page("Zerodha credentials saved", "Saved securely. The old Zerodha session was cleared.", '<p><a href="/zerodha/login">Connect Zerodha now</a></p>'))

    def _save_ollama(self, params: dict[str, list[str]]) -> None:
        base_url = params.get("ollama_base_url", [""])[0].strip()
        model = params.get("ollama_model", [""])[0].strip()
        api_key = params.get("ollama_api_key", [""])[0].strip()
        try:
            self.ollama_store.save(OllamaCredentials(base_url=base_url, model=model, api_key=api_key))
            self.operations.append_event(
                "ai", "OLLAMA_CLOUD_CREDENTIALS_UPDATED", {"base_url": base_url, "model": model}
            )
        except ValueError as exc:
            _write_html(self, 400, _message_page("Invalid Ollama Cloud settings", str(exc)))
            return
        _write_html(self, 200, _message_page("Ollama Cloud saved", "Remote Ollama configuration was stored securely. No local Ollama fallback is enabled."))

    def _switch_mode(self, params: dict[str, list[str]]) -> None:
        raw_mode = params.get("desired_mode", [""])[0].strip().lower()
        try:
            desired = AppMode(raw_mode)
        except ValueError:
            _write_html(self, 400, _message_page("Invalid mode", "Choose paper or live mode."))
            return
        if desired == AppMode.PAPER:
            self.mode_store.save(AppMode.PAPER)
            self.operations.append_event("runtime", "MODE_SWITCHED", {"mode": "paper"})
            _write_html(self, 200, _message_page("Paper mode enabled", "The next runtime cycle will use fake money with real Zerodha market data."))
            return
        if desired != AppMode.LIVE:
            _write_html(self, 400, _message_page("Invalid mode", "Only paper and live modes can run continuously."))
            return
        missing: list[str] = []
        if self._credentials() is None:
            missing.append("Zerodha API credentials")
        if not self._session_valid():
            missing.append("a current Zerodha login session")
        if not self._ollama_configured():
            missing.append("Ollama Cloud credentials")
        uncertain = [
            record
            for record in LiveOrderLedger(self.data_dir / "live-orders.sqlite3").pending()
            if not record.broker_order_id and record.status in {"UNKNOWN", "PENDING_SEND"}
        ]
        if uncertain:
            missing.append("reconciliation of an uncertain previous live order")
        safety = self.operations.get_safety_state()
        if safety.safe_mode:
            missing.append(f"clearing safe mode ({safety.reason})")
        if missing:
            _write_html(
                self,
                409,
                _message_page(
                    "Live mode not ready",
                    "Before switching to real money, configure " + ", ".join(missing) + ".",
                ),
            )
            return
        self.mode_store.save(AppMode.LIVE)
        self.operations.append_event("runtime", "MODE_SWITCHED", {"mode": "live"})
        _write_html(
            self,
            200,
            _message_page(
                "REAL MONEY mode enabled",
                "The next market-open runtime cycle can place real Zerodha orders using the same AI and deterministic risk pipeline as paper mode.",
            ),
        )

    def _export_diagnostic(self) -> None:
        content = build_diagnostic_export(self.data_dir, self.settings.starting_cash)
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        filename = f"ai-stock-trading-diagnostic-{stamp}.json"
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _handle_zerodha_callback(self, query: str) -> None:
        params = parse_qs(query)
        status = params.get("status", [""])[0]
        request_token = params.get("request_token", [""])[0]
        if status and status.lower() != "success":
            _write_html(self, 400, _message_page("Zerodha login failed", "Zerodha did not return a successful login status."))
            return
        if not request_token:
            _write_html(self, 400, _message_page("Missing request token", "The Zerodha callback did not include a request_token."))
            return
        credentials = self._credentials()
        if credentials is None:
            _write_html(self, 503, _message_page("Zerodha credentials not configured", "Save the API key and secret from the dashboard first."))
            return
        try:
            session = ZerodhaAuthClient(credentials.api_key, credentials.api_secret).exchange_request_token(request_token)
            self.session_store.save(session)
            self.operations.append_event(
                "broker", "ZERODHA_SESSION_CONNECTED", {"user_id": session.user_id, "expires_at": session.expires_at.isoformat()}
            )
        except Exception:
            _write_html(self, 502, _message_page("Zerodha session failed", "The request token could not be exchanged. Check the application credentials and try again."))
            return
        _write_html(self, 200, _message_page("Zerodha connected", f"Market-data session connected for {session.user_id}. It expires at {session.expires_at.isoformat()}."))

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    settings = Settings()
    DashboardServerHandler.settings = settings
    ThreadingHTTPServer((settings.dashboard_bind_host, settings.dashboard_port), DashboardServerHandler).serve_forever()


if __name__ == "__main__":
    main()
