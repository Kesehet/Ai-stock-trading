from __future__ import annotations

import json
import logging
import struct
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from threading import Event, Lock
from typing import Any
from urllib.parse import urlencode

from websockets.exceptions import ConnectionClosed
from websockets.sync.client import ClientConnection, connect

from app.microstructure import BookLevel, BookTick
from app.scheduler import IST

logger = logging.getLogger("ai-stock-trading.kite-depth")
KITE_WS_BASE = "wss://ws.kite.trade"
_FULL_PACKET_BYTES = 184
_DEPTH_OFFSET = 64
_DEPTH_LEVEL_BYTES = 12

StateCallback = Callable[[str, str], None]
TickCallback = Callable[[list[BookTick]], None]


def parse_binary_frame(frame: bytes, symbols_by_token: dict[int, str]) -> list[BookTick]:
    """Parse documented Kite full-mode NSE cash packets.

    Heartbeats, truncated frames and packet types other than the 184-byte regular
    full quote are ignored. This parser never handles order messages.
    """
    if len(frame) <= 1:
        return []
    if len(frame) < 2:
        return []
    packet_count = _uint16(frame, 0)
    offset = 2
    ticks: list[BookTick] = []
    for _ in range(packet_count):
        if offset + 2 > len(frame):
            break
        packet_length = _uint16(frame, offset)
        offset += 2
        end = offset + packet_length
        if packet_length <= 0 or end > len(frame):
            break
        packet = frame[offset:end]
        offset = end
        if len(packet) != _FULL_PACKET_BYTES:
            continue
        tick = parse_full_packet(packet, symbols_by_token)
        if tick is not None:
            ticks.append(tick)
    return ticks


def parse_full_packet(packet: bytes, symbols_by_token: dict[int, str]) -> BookTick | None:
    if len(packet) != _FULL_PACKET_BYTES:
        return None
    token = _uint32(packet, 0)
    symbol = symbols_by_token.get(token)
    if symbol is None:
        return None

    last_price = _uint32(packet, 4) / 100.0
    last_quantity = _uint32(packet, 8)
    volume = _uint32(packet, 16)
    timestamp_seconds = _uint32(packet, 60)
    if last_price <= 0:
        return None

    bids: list[BookLevel] = []
    asks: list[BookLevel] = []
    for index in range(10):
        start = _DEPTH_OFFSET + index * _DEPTH_LEVEL_BYTES
        quantity = _uint32(packet, start)
        price = _uint32(packet, start + 4) / 100.0
        orders = _uint16(packet, start + 8)
        if price <= 0:
            continue
        level = BookLevel(price=price, quantity=quantity, orders=orders)
        if index < 5:
            bids.append(level)
        else:
            asks.append(level)
    if not bids or not asks:
        return None

    timestamp = (
        datetime.fromtimestamp(timestamp_seconds, tz=UTC).astimezone(IST)
        if timestamp_seconds > 0
        else datetime.now(IST)
    )
    return BookTick(
        symbol=symbol,
        timestamp=timestamp,
        last_price=last_price,
        last_quantity=last_quantity,
        volume=volume,
        bids=tuple(bids),
        asks=tuple(asks),
    )


class KiteDepthStream:
    """Read-only Kite full-depth WebSocket consumer with bounded reconnects.

    The only outbound messages are subscription and market-data mode requests.
    Text frames, including potential order postbacks, are ignored.
    """

    def __init__(
        self,
        api_key: str,
        access_token: str,
        symbols_by_token: dict[int, str],
        *,
        reconnect_max_seconds: float = 30.0,
    ) -> None:
        if not api_key.strip() or not access_token.strip():
            raise ValueError("Kite API key and access token are required")
        if not symbols_by_token:
            raise ValueError("at least one instrument token is required")
        self.api_key = api_key.strip()
        self.access_token = access_token.strip()
        self.symbols_by_token = dict(symbols_by_token)
        self.reconnect_max_seconds = reconnect_max_seconds
        self._stop = Event()
        self._connection: ClientConnection | None = None
        self._connection_lock = Lock()

    @property
    def url(self) -> str:
        query = urlencode({"api_key": self.api_key, "access_token": self.access_token})
        return f"{KITE_WS_BASE}?{query}"

    def stop(self) -> None:
        self._stop.set()
        with self._connection_lock:
            connection = self._connection
        if connection is not None:
            try:
                connection.close()
            except Exception:
                logger.exception("failed to close Kite depth websocket cleanly")

    def run(self, on_ticks: TickCallback, on_state: StateCallback | None = None) -> None:
        delay = 1.0
        while not self._stop.is_set():
            try:
                self._run_connection(on_ticks, on_state)
                delay = 1.0
            except (ConnectionClosed, OSError, TimeoutError) as exc:
                if self._stop.is_set():
                    break
                if on_state is not None:
                    on_state("disconnected", str(exc))
                self._stop.wait(delay)
                delay = min(max(delay * 2.0, 1.0), self.reconnect_max_seconds)
            except Exception as exc:
                if self._stop.is_set():
                    break
                logger.exception("unexpected Kite depth stream failure")
                if on_state is not None:
                    on_state("error", str(exc))
                self._stop.wait(delay)
                delay = min(max(delay * 2.0, 1.0), self.reconnect_max_seconds)

    def _run_connection(
        self,
        on_ticks: TickCallback,
        on_state: StateCallback | None,
    ) -> None:
        with connect(
            self.url,
            open_timeout=10,
            ping_interval=20,
            ping_timeout=20,
            close_timeout=5,
            max_size=2 * 1024 * 1024,
        ) as websocket:
            with self._connection_lock:
                self._connection = websocket
            try:
                self._subscribe(websocket, tuple(self.symbols_by_token))
                if on_state is not None:
                    on_state("connected", "")
                while not self._stop.is_set():
                    try:
                        message = websocket.recv(timeout=1.0)
                    except TimeoutError:
                        continue
                    if isinstance(message, bytes):
                        ticks = parse_binary_frame(message, self.symbols_by_token)
                        if ticks:
                            on_ticks(ticks)
                    elif isinstance(message, str):
                        self._handle_text_message(message, on_state)
            finally:
                with self._connection_lock:
                    self._connection = None

    @staticmethod
    def _subscribe(websocket: ClientConnection, tokens: Sequence[int]) -> None:
        websocket.send(json.dumps({"a": "subscribe", "v": list(tokens)}, separators=(",", ":")))
        websocket.send(
            json.dumps(
                {"a": "mode", "v": ["full", list(tokens)]},
                separators=(",", ":"),
            )
        )

    @staticmethod
    def _handle_text_message(message: str, on_state: StateCallback | None) -> None:
        # Kite can send order postbacks over the same socket. This market-data
        # service deliberately ignores every text action and never acts on it.
        try:
            payload: Any = json.loads(message)
        except json.JSONDecodeError:
            return
        if not isinstance(payload, dict):
            return
        message_type = str(payload.get("type") or "")
        if message_type == "error" and on_state is not None:
            on_state("error", str(payload.get("data") or payload.get("message") or "Kite error"))


def _uint16(buffer: bytes, offset: int) -> int:
    return int(struct.unpack_from(">H", buffer, offset)[0])


def _uint32(buffer: bytes, offset: int) -> int:
    return int(struct.unpack_from(">I", buffer, offset)[0])
