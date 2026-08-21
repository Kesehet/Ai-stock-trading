# ruff: noqa: I001
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import UTC, date, datetime
from io import BytesIO, StringIO, TextIOWrapper
from zipfile import ZipFile

import httpx

from app.market_data import Candle


NSE_UDIFF_URL = (
    "https://nsearchives.nseindia.com/content/cm/"
    "BhavCopy_NSE_CM_0_0_0_{yyyymmdd}_F_0000.csv.zip"
)


def _first(row: dict[str, str], *names: str) -> str:
    normalized = {key.strip().upper(): value for key, value in row.items() if key is not None}
    for name in names:
        value = normalized.get(name.upper())
        if value is not None and value.strip():
            return value.strip()
    return ""


def _number(row: dict[str, str], *names: str) -> float:
    raw = _first(row, *names).replace(",", "")
    return float(raw) if raw else 0.0


def _timestamp(row: dict[str, str], trading_date: date) -> datetime:
    raw = _first(row, "TradDt", "TRADE_DATE", "TIMESTAMP", "DATE1")
    if raw:
        for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d-%b-%Y", "%d-%b-%y"):
            try:
                return datetime.strptime(raw, fmt).replace(tzinfo=UTC)
            except ValueError:
                continue
    return datetime.combine(trading_date, datetime.min.time(), tzinfo=UTC)


def parse_udiff_csv(content: str, trading_date: date) -> list[Candle]:
    rows = csv.DictReader(StringIO(content))
    candles: list[Candle] = []
    for row in rows:
        symbol = _first(row, "TckrSymb", "SYMBOL", "Symbol").upper()
        series = _first(row, "SctySrs", "SERIES", "Series").upper()
        if not symbol or (series and series != "EQ"):
            continue
        open_price = _number(row, "OpnPric", "OPEN", "OPEN_PRICE")
        high = _number(row, "HghPric", "HIGH", "HIGH_PRICE")
        low = _number(row, "LwPric", "LOW", "LOW_PRICE")
        close = _number(row, "ClsPric", "CLOSE", "CLOSE_PRICE")
        volume = _number(row, "TtlTradgVol", "TOTTRDQTY", "VOLUME", "TTL_TRD_QNTY")
        if min(open_price, high, low, close) <= 0:
            continue
        candles.append(
            Candle(
                symbol=symbol,
                timestamp=_timestamp(row, trading_date),
                open=open_price,
                high=high,
                low=low,
                close=close,
                volume=volume,
            )
        )
    return candles


def parse_udiff_zip(payload: bytes, trading_date: date) -> list[Candle]:
    with ZipFile(BytesIO(payload)) as archive:
        names = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        if not names:
            raise ValueError("NSE bhavcopy ZIP did not contain a CSV")
        with archive.open(names[0]) as raw:
            with TextIOWrapper(raw, encoding="utf-8-sig") as text:
                return parse_udiff_csv(text.read(), trading_date)


@dataclass(frozen=True)
class NSEBhavcopySource:
    url_template: str = NSE_UDIFF_URL
    timeout_seconds: float = 30.0

    def url_for(self, trading_date: date) -> str:
        return self.url_template.format(yyyymmdd=trading_date.strftime("%Y%m%d"))

    def fetch(self, trading_date: date) -> list[Candle]:
        with httpx.Client(timeout=self.timeout_seconds, follow_redirects=True) as client:
            response = client.get(
                self.url_for(trading_date),
                headers={
                    "User-Agent": "Mozilla/5.0 ai-stock-trading/0.1",
                    "Accept": "application/zip,application/octet-stream,*/*",
                    "Accept-Language": "en-IN,en;q=0.9",
                },
            )
            response.raise_for_status()
        return parse_udiff_zip(response.content, trading_date)
