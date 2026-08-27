from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

import httpx

from app.models import Quote


class QuoteProvider(Protocol):
    def get_quote(self, symbol: str) -> Quote: ...


class ZerodhaQuoteProvider:
    """Read-only Zerodha market-data adapter used by paper mode.

    It intentionally exposes quotes only. Order placement lives behind the
    separate live broker adapter so paper mode can never place real orders.
    """

    def __init__(
        self,
        api_key: str,
        access_token: str,
        *,
        base_url: str = "https://api.kite.trade",
        timeout_seconds: float = 10.0,
    ) -> None:
        if not api_key or not access_token:
            raise ValueError("Zerodha quote provider requires API key and access token")
        self.api_key = api_key
        self.access_token = access_token
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def get_quote(self, symbol: str) -> Quote:
        instrument = f"NSE:{symbol.upper()}"
        headers = {
            "X-Kite-Version": "3",
            "Authorization": f"token {self.api_key}:{self.access_token}",
        }
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.get(
                f"{self.base_url}/quote/ltp",
                params={"i": instrument},
                headers=headers,
            )
            response.raise_for_status()
            payload = response.json()
        data = payload.get("data", {}).get(instrument)
        if not isinstance(data, dict):
            raise ValueError(f"Zerodha returned no quote for {instrument}")
        last_price = data.get("last_price")
        if not isinstance(last_price, int | float) or last_price <= 0:
            raise ValueError(f"Zerodha returned invalid price for {instrument}")
        return Quote(symbol=symbol.upper(), last_price=float(last_price), as_of=datetime.now(UTC))
