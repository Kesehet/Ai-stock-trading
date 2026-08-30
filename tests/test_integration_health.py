from __future__ import annotations

from datetime import datetime, timedelta

import httpx

from app.integration_dashboard import render_integrations_page
from app.integration_health import IntegrationCheck, check_google_news, check_ollama, check_zerodha
from app.zerodha_session import IST, ZerodhaSession


def test_zerodha_health_validates_authenticated_profile() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "token key:access"
        return httpx.Response(200, json={"status": "success", "data": {"user_id": "AB123"}})

    now = datetime.now(IST)
    session = ZerodhaSession(
        access_token="access",
        user_id="AB123",
        login_time=now,
        expires_at=now + timedelta(hours=1),
    )
    result = check_zerodha("key", session, transport=httpx.MockTransport(handler))
    assert result.status == "connected"


def test_ollama_rate_limit_is_reported_as_degraded_not_disconnected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/generate"
        assert request.headers["Authorization"] == "Bearer secret"
        return httpx.Response(429, json={"error": "rate limit"})

    result = check_ollama(
        "https://ollama.example",
        "model-a",
        "secret",
        transport=httpx.MockTransport(handler),
    )
    assert result.status == "degraded"
    assert "rate limiting" in result.detail


def test_google_news_and_page_rendering() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<?xml version='1.0'?><rss><channel /></rss>")

    news = check_google_news(transport=httpx.MockTransport(handler))
    assert news.status == "connected"
    page = render_integrations_page(
        {"zerodha": False, "ollama": True, "google_news": True, "nse_archives": True},
        [
            news,
            IntegrationCheck("ollama", "Ollama Cloud", "connected", "OK", 12),
        ],
        admin_enabled=True,
    )
    assert "Integrations &amp; Connection Health" in page
    assert "Google News RSS" in page
    assert "NSE Archives" in page
    assert "Test all integrations" in page
