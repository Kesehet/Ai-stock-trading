from __future__ import annotations

import argparse
from getpass import getpass
from pathlib import Path

from app.config import Settings
from app.operations import OperationsStore
from app.zerodha_session import ZerodhaAuthClient, ZerodhaSessionStore

SESSION_SAFE_MODE_REASON = "ZERODHA_SESSION_MISSING_OR_EXPIRED"


def _stores(settings: Settings) -> tuple[ZerodhaSessionStore, OperationsStore]:
    data_dir = Path(settings.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    return (
        ZerodhaSessionStore(data_dir / "zerodha-session.json"),
        OperationsStore(data_dir / "operations.sqlite3"),
    )


def _auth_client(settings: Settings) -> ZerodhaAuthClient:
    return ZerodhaAuthClient(
        settings.zerodha_api_key,
        settings.zerodha_api_secret.get_secret_value(),
    )


def login_url(settings: Settings) -> None:
    print(_auth_client(settings).login_url())


def exchange(settings: Settings) -> None:
    request_token = getpass("Zerodha request_token: ").strip()
    session = _auth_client(settings).exchange_request_token(request_token)
    session_store, operations = _stores(settings)
    session_store.save(session)
    operations.append_event(
        "broker_auth",
        "ZERODHA_SESSION_REFRESHED",
        {"user_id": session.user_id, "expires_at": session.expires_at.isoformat()},
    )
    state = operations.get_safety_state()
    if state.safe_mode and state.reason == SESSION_SAFE_MODE_REASON:
        operations.set_safe_mode(False, "")
    print(f"Zerodha session stored for {session.user_id}; expires {session.expires_at.isoformat()}")


def status(settings: Settings) -> None:
    session_store, operations = _stores(settings)
    session = session_store.load()
    state = operations.get_safety_state()
    if session is None:
        print("session=missing")
    else:
        print(f"session_user={session.user_id}")
        print(f"session_expires={session.expires_at.isoformat()}")
        print(f"session_valid={str(session.is_valid()).lower()}")
    print(f"safe_mode={str(state.safe_mode).lower()}")
    if state.safe_mode:
        print(f"safe_mode_reason={state.reason}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Zerodha session administration")
    parser.add_argument("command", choices=("login-url", "exchange", "status"))
    args = parser.parse_args()
    settings = Settings()
    if args.command == "login-url":
        login_url(settings)
    elif args.command == "exchange":
        exchange(settings)
    else:
        status(settings)


if __name__ == "__main__":
    main()
