from __future__ import annotations

import logging
import signal
from datetime import datetime
from pathlib import Path
from threading import Event, Thread
from time import time

from app.config import Settings
from app.nse_calendar import nse_capital_market_calendar
from app.operations import OperationsStore
from app.production_trader import ProductionAutonomousTrader
from app.scheduler import IST, MarketPhase

logger = logging.getLogger("ai-stock-trading.runtime")
_stop = Event()


def _handle_signal(signum: int, _frame: object) -> None:
    logger.info("received signal %s; stopping", signum)
    _stop.set()


def _write_heartbeat(path: Path) -> None:
    path.write_text(str(int(time())), encoding="utf-8")


def _heartbeat_worker(path: Path, stop: Event, interval_seconds: float = 5.0) -> None:
    """Maintain liveness independently from slow market-data/AI work."""
    while not stop.is_set():
        try:
            _write_heartbeat(path)
        except OSError:
            logger.exception("failed to write runtime heartbeat")
        stop.wait(interval_seconds)


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
    trader = ProductionAutonomousTrader(settings)
    previous_phase: MarketPhase | None = None

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    heartbeat_thread = Thread(
        target=_heartbeat_worker,
        args=(heartbeat, _stop),
        name="runtime-heartbeat",
        daemon=True,
    )
    heartbeat_thread.start()

    operations.append_event(
        "runtime",
        "STARTED",
        {
            "default_mode": settings.app_mode.value,
            "universe_mode": "dynamic_nse" if settings.dynamic_universe else "watchlist_override",
        },
    )
    logger.info(
        "autonomous runtime started; universe=%s",
        "dynamic_nse" if settings.dynamic_universe else "watchlist_override",
    )

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
        _stop.wait(settings.quote_poll_seconds)

    operations.append_event("runtime", "STOPPED", {})
    heartbeat_thread.join(timeout=2.0)
    heartbeat.unlink(missing_ok=True)
    logger.info("runtime stopped")


if __name__ == "__main__":
    main()
