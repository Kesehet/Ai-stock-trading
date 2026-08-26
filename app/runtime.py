from __future__ import annotations

import logging
import signal
from datetime import datetime
from pathlib import Path
from threading import Event
from time import sleep, time

from app.autonomous_trader import AutonomousTrader
from app.config import Settings
from app.nse_calendar import nse_capital_market_calendar
from app.operations import OperationsStore
from app.scheduler import IST, MarketPhase

logger = logging.getLogger("ai-stock-trading.runtime")
_stop = Event()


def _handle_signal(signum: int, _frame: object) -> None:
    logger.info("received signal %s; stopping", signum)
    _stop.set()


def _write_heartbeat(path: Path) -> None:
    path.write_text(str(int(time())), encoding="utf-8")


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
    calendar = nse_capital_market_calendar()
    trader = AutonomousTrader(settings)
    previous_phase: MarketPhase | None = None

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    operations.append_event("runtime", "STARTED", {"default_mode": settings.app_mode.value})
    logger.info("autonomous runtime started")

    while not _stop.is_set():
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
        try:
            trader.tick(now)
        except Exception:
            logger.exception("autonomous trading tick failed")
            operations.append_event(
                "runtime",
                "TICK_FAILED",
                {"as_of": now.isoformat()},
                now,
            )
        _write_heartbeat(heartbeat)
        sleep(settings.quote_poll_seconds)

    operations.append_event("runtime", "STOPPED", {})
    heartbeat.unlink(missing_ok=True)
    logger.info("runtime stopped")


if __name__ == "__main__":
    main()
