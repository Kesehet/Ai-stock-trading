from __future__ import annotations

import logging
import signal
from datetime import datetime
from pathlib import Path
from threading import Event
from time import sleep, time

from app.config import AppMode, Settings
from app.nse_calendar import nse_capital_market_calendar
from app.operations import OperationsStore
from app.scheduler import IST, MarketPhase
from app.zerodha_session import ZerodhaSessionStore

logger = logging.getLogger("ai-stock-trading.runtime")
_stop = Event()


def _handle_signal(signum: int, _frame: object) -> None:
    logger.info("received signal %s; stopping", signum)
    _stop.set()


def _write_heartbeat(path: Path) -> None:
    path.write_text(str(int(time())), encoding="utf-8")


def _enforce_live_session_safety(
    session_store: ZerodhaSessionStore,
    operations: OperationsStore,
) -> bool:
    session = session_store.load()
    if session is not None and session.is_valid():
        return True
    state = operations.get_safety_state()
    if not state.safe_mode:
        operations.set_safe_mode(True, "ZERODHA_SESSION_MISSING_OR_EXPIRED")
    return False


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    settings = Settings()
    heartbeat = Path(settings.heartbeat_path)
    heartbeat.parent.mkdir(parents=True, exist_ok=True)
    data_dir = Path(settings.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    operations = OperationsStore(data_dir / "operations.sqlite3")
    session_store = ZerodhaSessionStore(data_dir / "zerodha-session.json")
    calendar = nse_capital_market_calendar()
    previous_phase: MarketPhase | None = None

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    operations.append_event("runtime", "STARTED", {"mode": settings.app_mode.value})
    logger.info("runtime starting in %s mode", settings.app_mode.value)
    if settings.app_mode == AppMode.LIVE:
        logger.warning(
            "LIVE mode is armed; broker execution adapter is still disabled in this build"
        )
        if not _enforce_live_session_safety(session_store, operations):
            logger.error("safe mode active: Zerodha session is missing or expired")

    while not _stop.is_set():
        if settings.app_mode == AppMode.LIVE:
            _enforce_live_session_safety(session_store, operations)
        now = datetime.now(IST)
        phase = calendar.phase_at(now)
        if phase != previous_phase:
            operations.append_event(
                "market",
                "PHASE_CHANGED",
                {"phase": phase.value, "as_of": now.isoformat()},
            )
            logger.info("market phase: %s", phase.value)
            previous_phase = phase
        _write_heartbeat(heartbeat)
        sleep(settings.runtime_poll_seconds)

    operations.append_event("runtime", "STOPPED", {"mode": settings.app_mode.value})
    heartbeat.unlink(missing_ok=True)
    logger.info("runtime stopped")


if __name__ == "__main__":
    main()
