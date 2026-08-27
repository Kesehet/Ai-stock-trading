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
from app.paper_fund import AutonomousPaperFund
from app.scheduler import IST, MarketPhase
from app.zerodha_market import ZerodhaQuoteProvider
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


def _paper_quote_provider(
    settings: Settings,
    session_store: ZerodhaSessionStore,
) -> ZerodhaQuoteProvider | None:
    access_token = settings.zerodha_access_token.get_secret_value()
    session = session_store.load()
    if session is not None and session.is_valid():
        access_token = session.access_token
    if not settings.zerodha_api_key or not access_token:
        return None
    return ZerodhaQuoteProvider(settings.zerodha_api_key, access_token)


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
    paper_fund: AutonomousPaperFund | None = None
    last_paper_cycle_monotonic = 0.0

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    operations.append_event("runtime", "STARTED", {"mode": settings.app_mode.value})
    logger.info("runtime starting in %s mode", settings.app_mode.value)

    if settings.app_mode == AppMode.PAPER:
        provider = _paper_quote_provider(settings, session_store)
        if provider is None:
            operations.append_event(
                "paper",
                "DISABLED_NO_ZERODHA_SESSION",
                {"reason": "API key/access token unavailable"},
            )
            logger.error("paper fund disabled: Zerodha quote session is unavailable")
        else:
            paper_fund = AutonomousPaperFund(
                data_dir=data_dir,
                starting_cash=settings.starting_cash,
                universe=settings.paper_universe,
                quote_provider=provider,
                operations=operations,
                ollama_base_url=settings.ollama_base_url,
                ollama_model=settings.ollama_model,
                max_position_pct=settings.max_position_pct,
                max_daily_loss_pct=settings.max_daily_loss_pct,
                max_open_positions=settings.max_open_positions,
                history_days=settings.paper_history_days,
                fallback_momentum=settings.paper_fallback_momentum,
                fallback_target_pct=settings.paper_fallback_target_pct,
            )
            operations.append_event(
                "paper",
                "ENABLED",
                {"universe": list(settings.paper_universe)},
            )
            logger.info("autonomous paper fund enabled for %s", settings.paper_universe)

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

        if paper_fund is not None and phase == MarketPhase.OPEN:
            monotonic_now = time()
            due = (
                last_paper_cycle_monotonic == 0.0
                or monotonic_now - last_paper_cycle_monotonic >= settings.paper_cycle_seconds
            )
            if due:
                try:
                    result = paper_fund.run_cycle(now)
                    logger.info(
                        "paper cycle complete: orders=%s holds=%s rejected=%s errors=%s",
                        result.orders,
                        result.holds,
                        result.rejected,
                        result.errors,
                    )
                except Exception:
                    logger.exception("paper fund cycle failed")
                    operations.append_event("paper", "CYCLE_FATAL_ERROR", {})
                finally:
                    last_paper_cycle_monotonic = monotonic_now

        _write_heartbeat(heartbeat)
        sleep(settings.runtime_poll_seconds)

    operations.append_event("runtime", "STOPPED", {"mode": settings.app_mode.value})
    heartbeat.unlink(missing_ok=True)
    logger.info("runtime stopped")


if __name__ == "__main__":
    main()
