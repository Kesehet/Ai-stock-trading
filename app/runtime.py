from __future__ import annotations

import json
import logging
import signal
from datetime import datetime
from logging.handlers import RotatingFileHandler
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


def _intraday_radar_worker(
    trader: ProductionAutonomousTrader,
    stop: Event,
    interval_seconds: float = 2.0,
) -> None:
    """Keep live opportunity discovery moving while AI research is busy."""
    while not stop.is_set():
        try:
            trader.intraday_radar_tick(datetime.now(IST))
        except Exception:
            logger.exception("intraday radar tick failed")
        stop.wait(interval_seconds)


def _configure_logging(data_dir: Path) -> None:
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not root.handlers:
        stream = logging.StreamHandler()
        stream.setFormatter(formatter)
        root.addHandler(stream)

    diagnostic_path = data_dir / "trader-diagnostics.log"
    rotating = RotatingFileHandler(
        diagnostic_path,
        maxBytes=2_000_000,
        backupCount=2,
        encoding="utf-8",
    )
    rotating.setLevel(logging.INFO)
    rotating.setFormatter(formatter)
    root.addHandler(rotating)


def _write_effective_config(settings: Settings, data_dir: Path) -> None:
    payload = {
        "dynamic_universe": settings.dynamic_universe,
        "decision_interval_seconds": settings.decision_interval_seconds,
        "quote_poll_seconds": settings.quote_poll_seconds,
        "max_ai_candidates": settings.max_ai_candidates,
        "max_position_pct": settings.max_position_pct,
        "max_daily_loss_pct": settings.max_daily_loss_pct,
        "max_open_positions": settings.max_open_positions,
        "min_buy_confidence": settings.min_buy_confidence,
        "paper_slippage_bps": settings.paper_slippage_bps,
        "universe_scan_limit": settings.universe_scan_limit,
        "intraday_scanner_enabled": settings.intraday_scanner_enabled,
        "intraday_scan_interval_seconds": settings.intraday_scan_interval_seconds,
        "intraday_scan_pool_limit": settings.intraday_scan_pool_limit,
        "intraday_scan_batch_size": settings.intraday_scan_batch_size,
        "intraday_hot_candidates": settings.intraday_hot_candidates,
        "intraday_hot_score_min": settings.intraday_hot_score_min,
        "intraday_interrupt_cooldown_seconds": (
            settings.intraday_interrupt_cooldown_seconds
        ),
    }
    target = data_dir / "effective-config.json"
    temporary = data_dir / ".effective-config.json.tmp"
    temporary.write_text(
        json.dumps(payload, separators=(",", ":"), sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(target)


def main() -> None:
    settings = Settings()
    heartbeat = Path(settings.heartbeat_path)
    heartbeat.parent.mkdir(parents=True, exist_ok=True)
    data_dir = Path(settings.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    _configure_logging(data_dir)
    _write_effective_config(settings, data_dir)

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

    radar_thread: Thread | None = None
    if settings.intraday_scanner_enabled:
        radar_thread = Thread(
            target=_intraday_radar_worker,
            args=(trader, _stop),
            name="intraday-radar",
            daemon=True,
        )
        radar_thread.start()

    operations.append_event(
        "runtime",
        "STARTED",
        {
            "default_mode": settings.app_mode.value,
            "universe_mode": "dynamic_nse" if settings.dynamic_universe else "watchlist_override",
            "intraday_radar_thread": settings.intraday_scanner_enabled,
        },
    )
    logger.info(
        "autonomous runtime started; universe=%s; intraday_radar=%s",
        "dynamic_nse" if settings.dynamic_universe else "watchlist_override",
        "enabled" if settings.intraday_scanner_enabled else "disabled",
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
    if radar_thread is not None:
        radar_thread.join(timeout=2.0)
    heartbeat.unlink(missing_ok=True)
    logger.info("runtime stopped")


if __name__ == "__main__":
    main()
