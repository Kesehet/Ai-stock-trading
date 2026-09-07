from __future__ import annotations

import json
import logging
import signal
from collections.abc import Mapping
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

import httpx
from kiteconnect import KiteTicker  # type: ignore[import-untyped]

from app.config import Settings
from app.microstructure_store import KiteFullTickAdapter, MicrostructureEventStore
from app.microstructure_universe import (
    AffordableInstrument,
    discover_affordable_universe,
    fetch_nse_equity_tokens,
)
from app.scheduler import IST
from app.zerodha_api import KITE_API_BASE, LiveMarketSnapshot
from app.zerodha_credentials import ZerodhaCredentialStore
from app.zerodha_session import ZerodhaSession, ZerodhaSessionStore

logger = logging.getLogger("ai-stock-trading.microstructure")


class ReadOnlyKiteMarketData:
    """GET-only Kite adapter used by the shadow recorder.

    This object intentionally exposes no order-placement methods.
    """

    def __init__(self, api_key: str, session: ZerodhaSession, timeout_seconds: float = 20.0) -> None:
        self.api_key = api_key
        self.session = session
        self.timeout_seconds = timeout_seconds

    @property
    def headers(self) -> dict[str, str]:
        return {
            "X-Kite-Version": "3",
            "Authorization": f"token {self.api_key}:{self.session.access_token}",
        }

    def market_snapshots(
        self,
        symbols: tuple[str, ...] | list[str],
    ) -> dict[str, LiveMarketSnapshot]:
        requested = [symbol.strip().upper() for symbol in symbols if symbol.strip()]
        if not requested:
            return {}
        params = [("i", f"NSE:{symbol}") for symbol in requested]
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.get(
                f"{KITE_API_BASE}/quote",
                headers=self.headers,
                params=params,
            )
            response.raise_for_status()
            payload = response.json()
        if payload.get("status") != "success":
            raise RuntimeError(str(payload.get("message") or "Kite quote request failed"))
        data = payload.get("data") or {}
        if not isinstance(data, Mapping):
            return {}

        result: dict[str, LiveMarketSnapshot] = {}
        for symbol in requested:
            item = data.get(f"NSE:{symbol}")
            if not isinstance(item, Mapping):
                continue
            ohlc = item.get("ohlc")
            if not isinstance(ohlc, Mapping):
                ohlc = {}
            last_price = _as_float(item.get("last_price"))
            previous_close = _as_float(ohlc.get("close"))
            if last_price <= 0:
                continue
            result[symbol] = LiveMarketSnapshot(
                symbol=symbol,
                last_price=last_price,
                open_price=_as_float(ohlc.get("open")) or last_price,
                high_price=_as_float(ohlc.get("high")) or last_price,
                low_price=_as_float(ohlc.get("low")) or last_price,
                previous_close=previous_close or last_price,
                volume=_as_float(item.get("volume")),
                as_of=_snapshot_time(item),
            )
        return result


class MicrostructureRecorder:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.data_dir = Path(settings.data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.session_store = ZerodhaSessionStore(self.data_dir / "zerodha-session.json")
        self.credential_store = ZerodhaCredentialStore(
            self.data_dir / "zerodha-credentials.json"
        )
        self.status_path = self.data_dir / "microstructure-status.json"
        self.event_path = self.data_dir / "microstructure-events.sqlite3"
        self._ticker: Any | None = None
        self._store: MicrostructureEventStore | None = None
        self._symbols_by_token: dict[int, str] = {}
        self._events_recorded = 0
        self._last_event_at: datetime | None = None
        self._last_status_write: datetime | None = None
        self._connected = False
        self._stop_requested = False

    def run(self) -> int:
        if not self.settings.microstructure_shadow_enabled:
            self._write_status("disabled", message="shadow recorder disabled")
            return 0

        api_key, session = self._load_session()
        if api_key is None or session is None:
            self._write_status("waiting_for_session", message="valid Zerodha session required")
            return 2

        market_data = ReadOnlyKiteMarketData(api_key, session)
        tokens = fetch_nse_equity_tokens(market_data)
        if self.settings.watchlist:
            wanted = set(self.settings.watchlist)
            tokens = {symbol: token for symbol, token in tokens.items() if symbol in wanted}
        universe = discover_affordable_universe(
            market_data,
            tokens,
            bankroll=self.settings.starting_cash,
            max_position_pct=self.settings.max_position_pct,
            min_price=self.settings.universe_min_price,
            limit=self.settings.microstructure_subscription_limit,
            batch_size=self.settings.microstructure_quote_batch_size,
        )
        if not universe:
            self._write_status("no_universe", message="no affordable liquid symbols discovered")
            return 3

        self._symbols_by_token = {item.token: item.symbol for item in universe}
        adapter = KiteFullTickAdapter(self._symbols_by_token)
        self._store = MicrostructureEventStore(
            self.event_path,
            max_events_per_symbol=self.settings.microstructure_max_events_per_symbol,
            prune_every=self.settings.microstructure_prune_every,
        )
        ticker = KiteTicker(api_key, session.access_token)
        self._ticker = ticker
        instrument_tokens = list(self._symbols_by_token)

        def on_connect(ws: Any, response: Any) -> None:
            del response
            self._connected = True
            ws.subscribe(instrument_tokens)
            ws.set_mode(ws.MODE_FULL, instrument_tokens)
            self._write_status("connected", universe=universe)

        def on_ticks(ws: Any, raw_ticks: list[dict[str, Any]]) -> None:
            del ws
            now = datetime.now(IST)
            converted = [
                tick
                for raw in raw_ticks
                if (tick := adapter.from_tick(raw, received_at=now)) is not None
            ]
            if not converted or self._store is None:
                return
            self._store.record_many(converted)
            self._events_recorded += len(converted)
            self._last_event_at = now
            if self._last_status_write is None or now - self._last_status_write >= timedelta(seconds=5):
                self._write_status("connected", universe=universe)

        def on_close(ws: Any, code: int, reason: str) -> None:
            del ws
            self._connected = False
            self._write_status("disconnected", universe=universe, message=f"{code}: {reason}")

        def on_error(ws: Any, code: int, reason: str) -> None:
            del ws
            self._write_status("error", universe=universe, message=f"{code}: {reason}")

        ticker.on_connect = on_connect
        ticker.on_ticks = on_ticks
        ticker.on_close = on_close
        ticker.on_error = on_error
        self._install_signal_handlers()
        self._write_status("connecting", universe=universe)
        try:
            ticker.connect(threaded=False)
        finally:
            if self._store is not None:
                self._store.close()
                self._store = None
            self._connected = False
            self._write_status(
                "stopped" if self._stop_requested else "disconnected",
                universe=universe,
            )
        return 0

    def request_stop(self) -> None:
        self._stop_requested = True
        ticker = self._ticker
        if ticker is not None:
            try:
                ticker.close()
            except Exception:
                logger.exception("failed to close microstructure websocket cleanly")

    def _load_session(self) -> tuple[str | None, ZerodhaSession | None]:
        api_key = self.settings.zerodha_api_key.strip()
        if not api_key:
            credentials = self.credential_store.load()
            api_key = credentials.api_key if credentials is not None else ""
        session = self.session_store.load()
        if not api_key or session is None or not session.is_valid():
            return None, None
        return api_key, session

    def _install_signal_handlers(self) -> None:
        def stop(signum: int, frame: Any) -> None:
            del signum, frame
            self.request_stop()

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)

    def _write_status(
        self,
        state: str,
        *,
        universe: tuple[AffordableInstrument, ...] = (),
        message: str = "",
    ) -> None:
        now = datetime.now(IST)
        payload = {
            "updated_at": now.isoformat(),
            "state": state,
            "connected": self._connected,
            "shadow_only": True,
            "events_recorded": self._events_recorded,
            "last_event_at": self._last_event_at.isoformat() if self._last_event_at else None,
            "database": str(self.event_path),
            "symbols": [item.symbol for item in universe],
            "symbol_count": len(universe),
            "position_cap_rupees": round(
                self.settings.starting_cash * self.settings.max_position_pct,
                2,
            ),
            "message": message,
        }
        self.status_path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=self.status_path.parent,
            prefix=".microstructure-status-",
            delete=False,
        ) as handle:
            json.dump(payload, handle, separators=(",", ":"), sort_keys=True)
            temporary = Path(handle.name)
        temporary.replace(self.status_path)
        self._last_status_write = now


def _snapshot_time(item: Mapping[str, object]) -> datetime:
    raw = item.get("timestamp") or item.get("last_trade_time")
    if isinstance(raw, datetime):
        return raw.replace(tzinfo=IST) if raw.tzinfo is None else raw
    if isinstance(raw, str):
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return datetime.now(IST)
        return parsed.replace(tzinfo=IST) if parsed.tzinfo is None else parsed
    return datetime.now(IST)


def _as_float(value: object) -> float:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float, str)):
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0
    return 0.0


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(MicrostructureRecorder(Settings()).run())


if __name__ == "__main__":
    main()
