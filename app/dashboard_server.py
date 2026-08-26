from __future__ import annotations

import html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from app.config import Settings
from app.dashboard import render_dashboard
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
        "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'",
    )
    handler.send_header("Content-Length", str(len(content)))
    handler.end_headers()
    handler.wfile.write(content)


def _message_page(title: str, message: str) -> str:
    return f"""<!doctype html>
<html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">
<title>{html.escape(title)}</title><style>
body{{margin:0;background:#07110d;color:#f3f7f4;font-family:system-ui,-apple-system,Segoe UI,sans-serif;display:grid;place-items:center;min-height:100vh}}
main{{width:min(620px,calc(100% - 32px));background:#0c1813;border:1px solid #20332a;border-radius:18px;padding:28px}}
h1{{margin:0 0 12px;font-size:24px}}p{{color:#a8bbb1;line-height:1.6}}a{{color:#42d392}}
</style></head><body><main><h1>{html.escape(title)}</h1><p>{html.escape(message)}</p><p><a href=\"/\">Back to dashboard</a></p></main></body></html>"""


class DashboardServerHandler(BaseHTTPRequestHandler):
    settings = Settings()

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

        if path != "/":
            self.send_error(404)
            return

        _write_html(self, 200, render_dashboard(self.settings))

    def _handle_zerodha_callback(self, query: str) -> None:
        params = parse_qs(query)
        status = params.get("status", [""])[0]
        request_token = params.get("request_token", [""])[0]

        if status and status.lower() != "success":
            _write_html(
                self,
                400,
                _message_page("Zerodha login failed", "Zerodha did not return a successful login status."),
            )
            return
        if not request_token:
            _write_html(
                self,
                400,
                _message_page("Missing request token", "The Zerodha callback did not include a request_token."),
            )
            return

        api_key = self.settings.zerodha_api_key
        api_secret = self.settings.zerodha_api_secret.get_secret_value()
        if not api_key or not api_secret:
            _write_html(
                self,
                503,
                _message_page(
                    "Zerodha credentials not configured",
                    "Add ZERODHA_API_KEY and ZERODHA_API_SECRET to the GitHub production secrets, then redeploy.",
                ),
            )
            return

        try:
            session = ZerodhaAuthClient(api_key, api_secret).exchange_request_token(request_token)
            store = ZerodhaSessionStore(Path(self.settings.data_dir) / "zerodha-session.json")
            store.save(session)
        except Exception:
            _write_html(
                self,
                502,
                _message_page(
                    "Zerodha session failed",
                    "The request token could not be exchanged. Check the application credentials and try logging in again.",
                ),
            )
            return

        _write_html(
            self,
            200,
            _message_page(
                "Zerodha connected",
                f"Market-data session connected for {session.user_id}. It expires at {session.expires_at.isoformat()}.",
            ),
        )

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    settings = Settings()
    DashboardServerHandler.settings = settings
    server = ThreadingHTTPServer(
        (settings.dashboard_bind_host, settings.dashboard_port),
        DashboardServerHandler,
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
