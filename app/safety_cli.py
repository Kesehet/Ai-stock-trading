from __future__ import annotations

import argparse
from pathlib import Path

from app.config import Settings
from app.operations import OperationsStore

CLEAR_CONFIRMATION = "I_HAVE_RESOLVED_THE_SAFETY_CAUSE"


def _store(settings: Settings) -> OperationsStore:
    return OperationsStore(Path(settings.data_dir) / "operations.sqlite3")


def status(settings: Settings) -> None:
    state = _store(settings).get_safety_state()
    print(f"safe_mode={str(state.safe_mode).lower()}")
    if state.safe_mode:
        print(f"reason={state.reason}")
        print(f"updated_at={state.updated_at.isoformat()}")


def trip(settings: Settings, reason: str) -> None:
    state = _store(settings).set_safe_mode(True, reason)
    print(f"safe mode enabled: {state.reason}")


def clear(settings: Settings, confirmation: str) -> None:
    if confirmation != CLEAR_CONFIRMATION:
        raise SystemExit("refusing to clear safe mode: confirmation phrase does not match")
    _store(settings).set_safe_mode(False, "")
    print("safe mode cleared")


def main() -> None:
    parser = argparse.ArgumentParser(description="Trading safety controls")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status")
    trip_parser = subparsers.add_parser("trip")
    trip_parser.add_argument("--reason", required=True)
    clear_parser = subparsers.add_parser("clear")
    clear_parser.add_argument("--confirmation", required=True)
    args = parser.parse_args()

    settings = Settings()
    if args.command == "status":
        status(settings)
    elif args.command == "trip":
        trip(settings, str(args.reason))
    else:
        clear(settings, str(args.confirmation))


if __name__ == "__main__":
    main()
