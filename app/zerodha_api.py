from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from io import StringIO
from typing import Any

import httpx

from app.brokers import ExecutionResult
from app.market_data import Candle
from app.models import OrderPlan, Position, Product, Quote, Side
from app.zerodha_session import IST, ZerodhaSession

KITE_API_BASE = "https://api.kite.trade"


@dataclass(frozen=True)
class InstrumentToken:
    symbol: str
    token: int


@dataclass(frozen=True)
class ZerodhaOrderStatus:
    order_id: str
    status: str
    filled_quantity: int
    pending_quantity: int
    average_price: float


class ZerodhaApi:
    """Minimal Kite Connect v3 market-data and live-broker adapter."""

    def __init__(
        self,
        api_key: str,
        session: ZerodhaSession,
        timeout_seconds: float = 20.0,
    ) -> None:
        if not api_key.strip() or not session.access_token.strip():
            raise ValueError("valid Zerodha API key and access token are required")
        self.api_key = api_key.strip()
        self.session = session
        self.timeout_seconds = timeout_seconds

    @property
    def headers(self) -> dict[str, str]:
        return {
            "X-Kite-Version": "3",
            "Authorization": f"token {self.api_key}:{self.session.access_token}",
        }

    def _get_json(self, path: str, params: Any = None) -> Any:
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.get(
                f"{KITE_API_BASE}{path}",
                headers=self.headers,
                params=params,
            )
            response.raise_for_status()
            payload = response.json()
        if payload.get("status") != "success":
            raise RuntimeError(str(payload.get("message") or "Zerodha API request failed"))
        return payload.get("data")

    def quotes(self, symbols: tuple[str, ...] | list[str]) -> dict[str, Quote]:
        requested = [symbol.strip().upper() for symbol in symbols if symbol.strip()]
        params = [("i", f"NSE:{symbol}") for symbol in requested]
        data = self._get_json("/quote", params=params)
        result: dict[str, Quote] = {}
        for symbol in requested:
            item = data.get(f"NSE:{symbol}") if isinstance(data, dict) else None
            if not item:
                continue
            raw_timestamp = item.get("timestamp") or item.get("last_trade_time")
            as_of = datetime.now(IST)
            if raw_timestamp:
                parsed = datetime.fromisoformat(str(raw_timestamp))
                as_of = parsed.replace(tzinfo=IST) if parsed.tzinfo is None else parsed
            result[symbol] = Quote(
                symbol=symbol,
                last_price=float(item["last_price"]),
                as_of=as_of,
            )
        return result

    def instrument_tokens(self, symbols: tuple[str, ...] | list[str]) -> dict[str, int]:
        wanted = {symbol.strip().upper() for symbol in symbols if symbol.strip()}
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.get(f"{KITE_API_BASE}/instruments/NSE", headers=self.headers)
            response.raise_for_status()
        rows = csv.DictReader(StringIO(response.text))
        tokens: dict[str, int] = {}
        for row in rows:
            symbol = str(row.get("tradingsymbol") or "").upper()
            if symbol not in wanted:
                continue
            segment = str(row.get("segment") or "").upper()
            instrument_type = str(row.get("instrument_type") or "").upper()
            if segment not in {"NSE", "NSE_EQ"} and instrument_type not in {"EQ", ""}:
                continue
            tokens[symbol] = int(row["instrument_token"])
        return tokens

    def historical_candles(
        self,
        symbol: str,
        token: int,
        start: datetime,
        end: datetime,
        interval: str = "day",
    ) -> list[Candle]:
        data = self._get_json(
            f"/instruments/historical/{token}/{interval}",
            params={
                "from": start.astimezone(IST).strftime("%Y-%m-%d %H:%M:%S"),
                "to": end.astimezone(IST).strftime("%Y-%m-%d %H:%M:%S"),
                "continuous": 0,
                "oi": 0,
            },
        )
        candles: list[Candle] = []
        for row in data.get("candles", []) if isinstance(data, dict) else []:
            timestamp = datetime.fromisoformat(str(row[0]))
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=IST)
            candles.append(
                Candle(
                    symbol=symbol.upper(),
                    timestamp=timestamp,
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    volume=float(row[5]),
                )
            )
        return candles

    def get_cash(self) -> float:
        data = self._get_json("/user/margins/equity")
        if not isinstance(data, dict):
            return 0.0
        available = data.get("available") or {}
        value = available.get("live_balance", data.get("net", available.get("cash", 0.0)))
        return float(value or 0.0)

    def get_positions(self) -> list[Position]:
        positions: dict[tuple[str, Product], Position] = {}
        holdings = self._get_json("/portfolio/holdings")
        for item in holdings or []:
            if str(item.get("exchange") or "") != "NSE":
                continue
            quantity = int(item.get("quantity") or 0) + int(item.get("t1_quantity") or 0)
            average_price = float(item.get("average_price") or 0.0)
            if quantity <= 0 or average_price <= 0:
                continue
            symbol = str(item["tradingsymbol"]).upper()
            positions[(symbol, Product.DELIVERY)] = Position(
                symbol=symbol,
                quantity=quantity,
                average_price=average_price,
                product=Product.DELIVERY,
            )

        position_payload = self._get_json("/portfolio/positions")
        for item in (position_payload or {}).get("net", []):
            if str(item.get("exchange") or "") != "NSE":
                continue
            if str(item.get("product") or "") != "MIS":
                continue
            quantity = int(item.get("quantity") or 0)
            average_price = float(item.get("average_price") or 0.0)
            if quantity <= 0 or average_price <= 0:
                continue
            symbol = str(item["tradingsymbol"]).upper()
            positions[(symbol, Product.INTRADAY)] = Position(
                symbol=symbol,
                quantity=quantity,
                average_price=average_price,
                product=Product.INTRADAY,
            )
        return list(positions.values())

    def order_status(self, order_id: str) -> ZerodhaOrderStatus | None:
        data = self._get_json(f"/orders/{order_id}")
        if not data:
            return None
        item = data[-1]
        return ZerodhaOrderStatus(
            order_id=str(item.get("order_id") or order_id),
            status=str(item.get("status") or "UNKNOWN"),
            filled_quantity=int(item.get("filled_quantity") or 0),
            pending_quantity=int(item.get("pending_quantity") or 0),
            average_price=float(item.get("average_price") or 0.0),
        )

    def place_order(self, plan: OrderPlan) -> ExecutionResult:
        if plan.limit_price is None:
            raise ValueError("live Zerodha orders require a limit price")
        if plan.side == Side.HOLD:
            raise ValueError("HOLD is not executable")
        product = "CNC" if plan.product == Product.DELIVERY else "MIS"
        form = {
            "tradingsymbol": plan.symbol,
            "exchange": "NSE",
            "transaction_type": plan.side.value,
            "order_type": "LIMIT",
            "quantity": str(plan.quantity),
            "product": product,
            "validity": "DAY",
            "price": f"{plan.limit_price:.2f}",
            "tag": "ai_stock_fund",
        }
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.post(
                f"{KITE_API_BASE}/orders/regular",
                headers=self.headers,
                data=form,
            )
            response.raise_for_status()
            payload = response.json()
        if payload.get("status") != "success":
            raise RuntimeError(str(payload.get("message") or "Zerodha order placement failed"))
        order_id = str((payload.get("data") or {})["order_id"])
        return ExecutionResult(
            order_id=order_id,
            status="SUBMITTED",
            filled_quantity=0,
            average_price=plan.limit_price,
        )
