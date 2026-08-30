# ruff: noqa: E501
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from time import perf_counter
from typing import Literal

import httpx

from app.nse_bhavcopy import NSE_UDIFF_URL
from app.zerodha_session import IST, ZerodhaSession

IntegrationStatus = Literal["connected", "degraded", "failed", "not_configured"]


@dataclass(frozen=True)
class IntegrationCheck:
    key: str
    name: str
    status: IntegrationStatus
    detail: str
    latency_ms: int | None = None

    def as_dict(self) -> dict[str, str | int | None]:
        return asdict(self)


def _latency_ms(started: float) -> int:
    return max(0, round((perf_counter() - started) * 1000))


def _failure(key: str, name: str, detail: str, started: float | None = None) -> IntegrationCheck:
    return IntegrationCheck(
        key=key,
        name=name,
        status="failed",
        detail=detail,
        latency_ms=_latency_ms(started) if started is not None else None,
    )


def check_zerodha(
    api_key: str,
    session: ZerodhaSession | None,
    *,
    timeout_seconds: float = 8.0,
    transport: httpx.BaseTransport | None = None,
) -> IntegrationCheck:
    key = "zerodha"
    name = "Zerodha Kite Connect"
    if not api_key.strip():
        return IntegrationCheck(key, name, "not_configured", "API credentials are not configured.")
    if session is None or not session.is_valid():
        return IntegrationCheck(
            key,
            name,
            "failed",
            "Credentials exist, but the Zerodha login session is missing or expired.",
        )

    started = perf_counter()
    try:
        with httpx.Client(timeout=timeout_seconds, transport=transport) as client:
            response = client.get(
                "https://api.kite.trade/user/profile",
                headers={
                    "X-Kite-Version": "3",
                    "Authorization": f"token {api_key.strip()}:{session.access_token}",
                },
            )
        if response.status_code in {401, 403}:
            return _failure(key, name, "Zerodha rejected the current session.", started)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or payload.get("status") != "success":
            return _failure(key, name, "Zerodha responded, but authentication was not successful.", started)
        return IntegrationCheck(
            key,
            name,
            "connected",
            "Authenticated Kite Connect API call succeeded.",
            _latency_ms(started),
        )
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        return _failure(key, name, f"Connection test failed: {type(exc).__name__}.", started)


def check_ollama(
    base_url: str,
    model: str,
    api_key: str,
    *,
    timeout_seconds: float = 20.0,
    transport: httpx.BaseTransport | None = None,
) -> IntegrationCheck:
    key = "ollama"
    name = "Ollama Cloud"
    if not base_url.strip() or not model.strip() or not api_key.strip():
        return IntegrationCheck(
            key,
            name,
            "not_configured",
            "Cloud URL, model and API key must all be configured.",
        )

    started = perf_counter()
    try:
        with httpx.Client(timeout=timeout_seconds, transport=transport) as client:
            response = client.post(
                f"{base_url.rstrip('/')}/api/generate",
                headers={"Authorization": f"Bearer {api_key.strip()}"},
                json={
                    "model": model.strip(),
                    "prompt": "Reply with OK.",
                    "stream": False,
                    "options": {"temperature": 0, "num_predict": 1},
                },
            )
        latency = _latency_ms(started)
        if response.status_code == 429:
            return IntegrationCheck(
                key,
                name,
                "degraded",
                "Ollama is reachable and currently rate limiting requests.",
                latency,
            )
        if response.status_code in {401, 403}:
            return _failure(key, name, "Ollama rejected the API key.", started)
        if response.status_code == 404:
            return _failure(key, name, "Ollama generate endpoint or configured model was not found.", started)
        if response.status_code >= 500:
            return IntegrationCheck(
                key,
                name,
                "degraded",
                f"Ollama is reachable but returned HTTP {response.status_code}.",
                latency,
            )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            return _failure(key, name, "Ollama returned an unexpected response body.", started)
        return IntegrationCheck(
            key,
            name,
            "connected",
            f"Authenticated generation succeeded for model {model.strip()}.",
            latency,
        )
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        return _failure(key, name, f"Connection test failed: {type(exc).__name__}.", started)


def check_google_news(
    *,
    timeout_seconds: float = 10.0,
    transport: httpx.BaseTransport | None = None,
) -> IntegrationCheck:
    key = "google_news"
    name = "Google News RSS"
    started = perf_counter()
    try:
        with httpx.Client(timeout=timeout_seconds, follow_redirects=True, transport=transport) as client:
            response = client.get(
                "https://news.google.com/rss/search?q=NSE%20stock%20India&hl=en-IN&gl=IN&ceid=IN:en",
                headers={"User-Agent": "ai-stock-trading/0.1 integration-health"},
            )
        response.raise_for_status()
        body = response.text.lower()
        if "<rss" not in body and "<feed" not in body:
            return _failure(key, name, "Google News responded without an RSS/Atom feed.", started)
        return IntegrationCheck(
            key,
            name,
            "connected",
            "India-focused company-news feed is reachable.",
            _latency_ms(started),
        )
    except httpx.HTTPError as exc:
        return _failure(key, name, f"Connection test failed: {type(exc).__name__}.", started)


def check_nse_archives(
    *,
    timeout_seconds: float = 10.0,
    transport: httpx.BaseTransport | None = None,
) -> IntegrationCheck:
    key = "nse_archives"
    name = "NSE Archives"
    today = datetime.now(IST).date()
    candidates = [today - timedelta(days=offset) for offset in range(1, 9)]
    candidates = [day for day in candidates if day.weekday() < 5]
    started = perf_counter()
    try:
        with httpx.Client(timeout=timeout_seconds, follow_redirects=True, transport=transport) as client:
            for trading_date in candidates:
                url = NSE_UDIFF_URL.format(yyyymmdd=trading_date.strftime("%Y%m%d"))
                with client.stream(
                    "GET",
                    url,
                    headers={
                        "User-Agent": "Mozilla/5.0 ai-stock-trading/0.1 integration-health",
                        "Accept": "application/zip,application/octet-stream,*/*",
                        "Range": "bytes=0-64",
                    },
                ) as response:
                    if response.status_code == 404:
                        continue
                    response.raise_for_status()
                    return IntegrationCheck(
                        key,
                        name,
                        "connected",
                        f"Bhavcopy archive is reachable ({trading_date.isoformat()}).",
                        _latency_ms(started),
                    )
        return _failure(key, name, "No recent weekday bhavcopy could be reached.", started)
    except httpx.HTTPError as exc:
        return _failure(key, name, f"Connection test failed: {type(exc).__name__}.", started)
