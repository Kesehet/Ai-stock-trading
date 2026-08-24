from __future__ import annotations

import logging
import signal
from pathlib import Path
from threading import Event
from time import sleep, time

from app.config import AppMode, Settings

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

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    logger.info("runtime starting in %s mode", settings.app_mode.value)
    if settings.app_mode == AppMode.LIVE:
        logger.warning(
            "LIVE mode is armed; broker execution adapter is still disabled in this build"
        )

    while not _stop.is_set():
        _write_heartbeat(heartbeat)
        sleep(settings.runtime_poll_seconds)

    heartbeat.unlink(missing_ok=True)
    logger.info("runtime stopped")


if __name__ == "__main__":
    main()
