from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, time, timedelta
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import httpx

IST = ZoneInfo("Asia/Kolkata")
KITE_LOGIN_URL = "https://kite.zerodha.com/connect/login"
KITE_SESSION_URL = "https://api.kite.trade/session/token"


@dataclass(frozen=True)
class ZerodhaSession:
    access_token: str
    user_id: str
    login_time: datetime
    expires_at: datetime

    def is_valid(self, now: datetime | None = None) -> bool:
        current = now or datetime.now(IST)
        if current.tzinfo is None:
            raise ValueError("session validation time must be timezone-aware")
        return current < self.expires_at


class ZerodhaSessionStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def save(self, session: ZerodhaSession) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            **asdict(session),
            "login_time": session.login_time.isoformat(),
            "expires_at": session.expires_at.isoformat(),
        }
        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=self.path.parent,
            prefix=".zerodha-session-",
            delete=False,
        ) as handle:
            json.dump(payload, handle)
            handle.flush()
            os.fchmod(handle.fileno(), 0o600)
            temp_path = Path(handle.name)
        temp_path.replace(self.path)
        self.path.chmod(0o600)

    def load(self) -> ZerodhaSession | None:
        if not self.path.exists():
            return None
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        return ZerodhaSession(
            access_token=str(payload["access_token"]),
            user_id=str(payload["user_id"]),
            login_time=datetime.fromisoformat(str(payload["login_time"])),
            expires_at=datetime.fromisoformat(str(payload["expires_at"])),
        )

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)


def zerodha_session_expiry(login_time: datetime) -> datetime:
    if login_time.tzinfo is None:
        raise ValueError("login_time must be timezone-aware")
    local = login_time.astimezone(IST)
    next_day = local.date() + timedelta(days=1)
    return datetime.combine(next_day, time(hour=6), tzinfo=IST)


def kite_checksum(api_key: str, request_token: str, api_secret: str) -> str:
    raw = f"{api_key}{request_token}{api_secret}".encode()
    return hashlib.sha256(raw).hexdigest()


class ZerodhaAuthClient:
    def __init__(
        self,
        api_key: str,
        api_secret: str,
        timeout_seconds: float = 20.0,
    ) -> None:
        if not api_key or not api_secret:
            raise ValueError("Zerodha API key and secret are required")
        self.api_key = api_key
        self.api_secret = api_secret
        self.timeout_seconds = timeout_seconds

    def login_url(self) -> str:
        return f"{KITE_LOGIN_URL}?{urlencode({'v': 3, 'api_key': self.api_key})}"

    def exchange_request_token(self, request_token: str) -> ZerodhaSession:
        if not request_token:
            raise ValueError("request_token is required")
        checksum = kite_checksum(self.api_key, request_token, self.api_secret)
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.post(
                KITE_SESSION_URL,
                headers={"X-Kite-Version": "3"},
                data={
                    "api_key": self.api_key,
                    "request_token": request_token,
                    "checksum": checksum,
                },
            )
            response.raise_for_status()
        payload = response.json()["data"]
        raw_login_time = payload.get("login_time")
        if raw_login_time:
            login_time = datetime.fromisoformat(str(raw_login_time)).replace(tzinfo=IST)
        else:
            login_time = datetime.now(IST)
        return ZerodhaSession(
            access_token=str(payload["access_token"]),
            user_id=str(payload["user_id"]),
            login_time=login_time,
            expires_at=zerodha_session_expiry(login_time),
        )
