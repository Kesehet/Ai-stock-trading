from __future__ import annotations

import csv
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from io import StringIO
from typing import Protocol

import httpx

from app.zerodha_api import KITE_API_BASE, LiveMarketSnapshot


class MarketSnapshotApi(Protocol):
    headers: Mapping[str, str]
    timeout_seconds: float

    def market_snapshots(
        self,
        symbols: tuple[str, ...] | list[str],
    ) -> dict[str, LiveMarketSnapshot]: ...


@dataclass(frozen=True)
class AffordableInstrument:
    symbol: str
    token: int
    last_price: float
    volume: float
    traded_value: float


def fetch_nse_equity_tokens(api: MarketSnapshotApi) -> dict[str, int]:
    """Fetch the NSE equity instrument master without any order capability."""
    with httpx.Client(timeout=api.timeout_seconds) as client:
        response = client.get(f"{KITE_API_BASE}/instruments/NSE", headers=dict(api.headers))
        response.raise_for_status()
    return parse_nse_equity_tokens(response.text)


def parse_nse_equity_tokens(content: str) -> dict[str, int]:
    rows = csv.DictReader(StringIO(content))
    tokens: dict[str, int] = {}
    for row in rows:
        exchange = str(row.get("exchange") or "").strip().upper()
        segment = str(row.get("segment") or "").strip().upper()
        instrument_type = str(row.get("instrument_type") or "").strip().upper()
        symbol = str(row.get("tradingsymbol") or "").strip().upper()
        raw_token = str(row.get("instrument_token") or "").strip()
        if exchange != "NSE" or segment not in {"NSE", "NSE_EQ"}:
            continue
        if instrument_type not in {"EQ", ""} or not symbol or not raw_token.isdigit():
            continue
        tokens[symbol] = int(raw_token)
    return tokens


def discover_affordable_universe(
    api: MarketSnapshotApi,
    tokens: Mapping[str, int],
    *,
    bankroll: float = 500.0,
    max_position_pct: float = 0.50,
    min_price: float = 20.0,
    limit: int = 100,
    batch_size: int = 400,
) -> tuple[AffordableInstrument, ...]:
    """Rank whole-share-executable equities by current traded value.

    This is only a data-subscription universe. It is not a trading recommendation.
    """
    if bankroll <= 0:
        raise ValueError("bankroll must be positive")
    if not 0 < max_position_pct <= 1:
        raise ValueError("max_position_pct must be in (0, 1]")
    if min_price < 0:
        raise ValueError("min_price cannot be negative")
    if limit < 1 or batch_size < 1:
        raise ValueError("limit and batch_size must be positive")

    position_cap = bankroll * max_position_pct
    symbols = sorted(tokens)
    candidates: list[AffordableInstrument] = []
    for batch in _chunks(symbols, batch_size):
        snapshots = api.market_snapshots(list(batch))
        for symbol, snapshot in snapshots.items():
            price = snapshot.last_price
            if price < min_price or price > position_cap or snapshot.volume <= 0:
                continue
            token = tokens.get(symbol.upper())
            if token is None:
                continue
            traded_value = price * snapshot.volume
            candidates.append(
                AffordableInstrument(
                    symbol=symbol.upper(),
                    token=token,
                    last_price=price,
                    volume=snapshot.volume,
                    traded_value=traded_value,
                )
            )

    candidates.sort(
        key=lambda item: (item.traded_value, item.volume, -item.last_price),
        reverse=True,
    )
    return tuple(candidates[:limit])


def _chunks(values: Sequence[str], size: int) -> list[Sequence[str]]:
    return [values[start : start + size] for start in range(0, len(values), size)]
