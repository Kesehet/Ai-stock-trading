from datetime import datetime
from zoneinfo import ZoneInfo

from app.zerodha_session import (
    ZerodhaSession,
    ZerodhaSessionStore,
    kite_checksum,
    zerodha_session_expiry,
)

IST = ZoneInfo("Asia/Kolkata")


def test_kite_checksum_matches_sha256_contract() -> None:
    assert kite_checksum("key", "token", "secret") == (
        "08a03d928417ea4085557933d3b187ff2a3515b039d6054dbd230c95d978a17a"
    )


def test_session_expires_at_6am_next_day() -> None:
    login = datetime(2026, 8, 25, 9, 30, tzinfo=IST)
    expiry = zerodha_session_expiry(login)
    assert expiry == datetime(2026, 8, 26, 6, 0, tzinfo=IST)


def test_session_store_round_trip_and_permissions(tmp_path) -> None:
    login = datetime(2026, 8, 25, 9, 30, tzinfo=IST)
    session = ZerodhaSession(
        access_token="session-token",
        user_id="AB1234",
        login_time=login,
        expires_at=zerodha_session_expiry(login),
    )
    path = tmp_path / "zerodha.json"
    store = ZerodhaSessionStore(path)

    store.save(session)
    loaded = store.load()

    assert loaded == session
    assert path.stat().st_mode & 0o777 == 0o600
    assert loaded is not None
    assert loaded.is_valid(datetime(2026, 8, 25, 12, 0, tzinfo=IST))
    assert not loaded.is_valid(datetime(2026, 8, 26, 6, 0, tzinfo=IST))
