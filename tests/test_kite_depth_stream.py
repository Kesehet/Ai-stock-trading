import struct
from datetime import UTC, datetime

from app.kite_depth_stream import parse_binary_frame
from app.scheduler import IST


def test_full_packet_parses_top_five_depth_and_exchange_timestamp() -> None:
    timestamp = int(datetime(2026, 9, 7, 3, 45, tzinfo=UTC).timestamp())
    packet = bytearray(184)
    struct.pack_into(">I", packet, 0, 12345)
    struct.pack_into(">I", packet, 4, 5005)
    struct.pack_into(">I", packet, 8, 25)
    struct.pack_into(">I", packet, 16, 123_456)
    struct.pack_into(">I", packet, 60, timestamp)

    for index in range(10):
        offset = 64 + index * 12
        if index < 5:
            price_paise = 5000 - index * 5
            quantity = 1000 - index * 50
        else:
            ask_index = index - 5
            price_paise = 5005 + ask_index * 5
            quantity = 200 + ask_index * 20
        struct.pack_into(">I", packet, offset, quantity)
        struct.pack_into(">I", packet, offset + 4, price_paise)
        struct.pack_into(">H", packet, offset + 8, 3)

    frame = struct.pack(">H", 1) + struct.pack(">H", len(packet)) + bytes(packet)
    ticks = parse_binary_frame(frame, {12345: "ABC"})

    assert len(ticks) == 1
    tick = ticks[0]
    assert tick.symbol == "ABC"
    assert tick.last_price == 50.05
    assert tick.last_quantity == 25
    assert tick.volume == 123_456
    assert tick.timestamp == datetime(2026, 9, 7, 9, 15, tzinfo=IST)
    assert len(tick.bids) == 5
    assert len(tick.asks) == 5
    assert tick.bids[0].price == 50.0
    assert tick.asks[0].price == 50.05
    assert tick.bids[0].quantity == 1000
    assert tick.asks[0].quantity == 200


def test_heartbeat_and_truncated_frames_are_ignored() -> None:
    assert parse_binary_frame(b"\x00", {1: "ABC"}) == []
    assert parse_binary_frame(b"\x00\x01\x00", {1: "ABC"}) == []


def test_unsubscribed_token_is_ignored() -> None:
    packet = bytearray(184)
    struct.pack_into(">I", packet, 0, 99999)
    struct.pack_into(">I", packet, 4, 5000)
    frame = struct.pack(">H", 1) + struct.pack(">H", len(packet)) + bytes(packet)

    assert parse_binary_frame(frame, {12345: "ABC"}) == []
