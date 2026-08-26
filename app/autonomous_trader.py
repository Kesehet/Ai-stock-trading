from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Protocol

from app.ai import OllamaClient
from app.brokers import ExecutionResult
from app.config import AppMode, Settings
from app.costs import ZERODHA_NSE_CASH_2026
from app.dashboard_store import DashboardSnapshotStore
from app.dashboard_store import PortfolioSnapshot as DashboardSnapshot
from app.evidence.store import EvidenceStore
from app.live_order_ledger import LiveOrderLedger
from app.managed_live_broker import ManagedLiveBroker
from app.market_data import HistoricalDataStore
from app.models import OrderPlan, Position, Product, Quote, Side, TradeIntent
from app.news_ingestion import CompanyNewsIngestor
from app.nse_calendar import nse_capital_market_calendar
from app.operations import OperationsStore
from app.persistent_paper import PersistentPaperBroker
from app.position_policy import PositionPolicyStore
from app.research_team import FundDecision, ResearchContextBuilder, ResearchTeam
from app.risk import PortfolioSnapshot, RiskEngine, RiskLimits
from app.runtime_mode import RuntimeModeStore
from app.runtime_state import RuntimeStateStore
from app.scheduler import IST, MarketPhase
from app.theses import Thesis, ThesisStore
from app.zerodha_api import ZerodhaApi
from app.zerodha_credentials import ZerodhaCredentialStore, ZerodhaCredentials
from app.zerodha_session import ZerodhaSessionStore

logger = logging.getLogger("ai-stock-trading.autonomous")


class PortfolioBroker(Protocol):
    def get_cash(self) -> float: ...
    def get_positions(self) -> list[Position]: ...
    def place_order(self, plan: OrderPlan) -> ExecutionResult: ...


class AutonomousTrader:
    """Always-on real-market loop shared by paper and live execution."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.data_dir = Path(settings.data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.operations = OperationsStore(self.data_dir / "operations.sqlite3")
        self.dashboard = DashboardSnapshotStore(self.data_dir / "dashboard.sqlite3")
        self.mode_store = RuntimeModeStore(
            self.data_dir / "runtime-mode.json",
            default_mode=settings.app_mode,
        )
        self.state_store = RuntimeStateStore(self.data_dir / "runtime-state.json")
        self.session_store = ZerodhaSessionStore(self.data_dir / "zerodha-session.json")
        self.credential_store = ZerodhaCredentialStore(
            self.data_dir / "zerodha-credentials.json"
        )
        self.evidence = EvidenceStore(self.data_dir / "evidence.sqlite3")
        self.news = CompanyNewsIngestor(self.evidence)
        self.market_data = HistoricalDataStore()
        self.theses = ThesisStore(self.data_dir / "theses.sqlite3")
        self.policies = PositionPolicyStore(self.data_dir / "position-policies.sqlite3")
        self.live_ledger = LiveOrderLedger(self.data_dir / "live-orders.sqlite3")
        self.paper_broker = PersistentPaperBroker(
            self.data_dir / "paper.sqlite3",
            starting_cash=settings.starting_cash,
            slippage_bps=settings.paper_slippage_bps,
            charge_schedule=ZERODHA_NSE_CASH_2026,
        )
        self.risk = RiskEngine(
            RiskLimits(
                max_position_pct=settings.max_position_pct,
                max_daily_loss_pct=settings.max_daily_loss_pct,
                max_open_positions=settings.max_open_positions,
                min_buy_confidence=settings.min_buy_confidence,
            )
        )
        self.calendar = nse_capital_market_calendar()
        self._history_warmed_date = ""
        self._last_nav_write: datetime | None = None
        self._last_mode: AppMode | None = None
        self._last_connection_state = ""

    def _credentials(self) -> ZerodhaCredentials | None:
        api_key = self.settings.zerodha_api_key.strip()
        api_secret = self.settings.zerodha_api_secret.get_secret_value().strip()
        if api_key and api_secret:
            return ZerodhaCredentials(api_key=api_key, api_secret=api_secret)
        return self.credential_store.load()

    def _api(self) -> ZerodhaApi | None:
        credentials = self._credentials()
        session = self.session_store.load()
        if credentials is None or session is None or not session.is_valid():
            state = (
                "missing_credentials"
                if credentials is None
                else "missing_or_expired_session"
            )
            if state != self._last_connection_state:
                self.operations.append_event(
                    "market_data",
                    "ZERODHA_UNAVAILABLE",
                    {"reason": state},
                )
                logger.warning("Zerodha unavailable: %s", state)
                self._last_connection_state = state
            return None
        self._last_connection_state = "connected"
        return ZerodhaApi(credentials.api_key, session)

    def _warm_history(self, api: ZerodhaApi, now: datetime) -> None:
        today = now.astimezone(IST).date().isoformat()
        if self._history_warmed_date == today:
            return
        tokens = api.instrument_tokens(self.settings.watchlist)
        start = now - timedelta(days=220)
        loaded = 0
        failed: list[str] = []
        for symbol in self.settings.watchlist:
            token = tokens.get(symbol)
            if token is None:
                failed.append(symbol)
                continue
            try:
                candles = api.historical_candles(
                    symbol,
                    token,
                    start,
                    now,
                    interval="day",
                )
            except Exception as exc:
                logger.warning("history warm failed for %s: %s", symbol, exc)
                failed.append(symbol)
                continue
            for candle in candles:
                self.market_data.add(candle)
            loaded += len(candles)
        self._history_warmed_date = today
        self.state_store.set_history_warm(now.astimezone(IST).date())
        self.operations.append_event(
            "market_data",
            "HISTORY_WARMED",
            {"candles": loaded, "failed_symbols": failed},
        )

    def _live_broker(self, api: ZerodhaApi) -> ManagedLiveBroker:
        return ManagedLiveBroker(
            api,
            self.live_ledger,
            self.settings.starting_cash,
            order_timeout_seconds=self.settings.live_order_timeout_seconds,
        )

    @staticmethod
    def _portfolio_symbols(positions: list[Position]) -> tuple[str, ...]:
        return tuple(dict.fromkeys(position.symbol for position in positions))

    def _quotes_for_portfolio(
        self,
        api: ZerodhaApi,
        positions: list[Position],
    ) -> dict[str, Quote]:
        symbols = tuple(
            dict.fromkeys((*self.settings.watchlist, *self._portfolio_symbols(positions)))
        )
        return api.quotes(symbols)

    def _valuation(
        self,
        broker: PortfolioBroker,
        quotes: dict[str, Quote],
        now: datetime,
    ) -> tuple[PortfolioSnapshot, DashboardSnapshot]:
        positions = broker.get_positions()
        cash = float(broker.get_cash())
        deployed = sum(position.quantity * position.average_price for position in positions)
        holdings_value = sum(
            position.quantity
            * (
                quotes[position.symbol].last_price
                if position.symbol in quotes
                else position.average_price
            )
            for position in positions
        )
        total_value = cash + holdings_value
        daily = self.state_store.ensure_daily_baseline(
            now.astimezone(IST).date(),
            total_value,
        )
        daily_pnl = total_value - daily.daily_start_equity
        return (
            PortfolioSnapshot(
                cash=cash,
                equity=total_value,
                open_positions=len(positions),
                daily_pnl=daily_pnl,
                positions=tuple(positions),
            ),
            DashboardSnapshot(
                captured_at=now,
                cash=cash,
                deployed=deployed,
                holdings_value=holdings_value,
                total_value=total_value,
            ),
        )

    def _write_nav(self, snapshot: DashboardSnapshot, now: datetime) -> None:
        if self._last_nav_write is not None:
            elapsed = (now - self._last_nav_write).total_seconds()
            if elapsed < 60:
                return
        self.dashboard.append(snapshot)
        self._last_nav_write = now

    def _candidate_score(self, symbol: str, now: datetime) -> float:
        candles = self.market_data.as_of(symbol, now, limit=21)
        if len(candles) < 2:
            return float("-inf")
        start = candles[0].close
        return (candles[-1].close / start) - 1 if start > 0 else float("-inf")

    def _candidates(
        self,
        positions: list[Position],
        now: datetime,
        *,
        allow_new_buys: bool,
    ) -> list[str]:
        held = list(dict.fromkeys(position.symbol for position in positions))
        if not allow_new_buys:
            return held
        held_set = set(held)
        ranked = sorted(
            (symbol for symbol in self.settings.watchlist if symbol not in held_set),
            key=lambda symbol: self._candidate_score(symbol, now),
            reverse=True,
        )
        return held + ranked[: self.settings.max_ai_candidates]

    def _decision_due(self, symbol: str, now: datetime) -> bool:
        raw = self.state_store.load().decisions.get(symbol.upper())
        if not raw:
            return True
        previous = datetime.fromisoformat(raw)
        return (now - previous).total_seconds() >= self.settings.decision_interval_seconds

    def _build_team(
        self,
        broker: PortfolioBroker,
        quotes: dict[str, Quote],
    ) -> ResearchTeam:
        llm = OllamaClient.from_settings(self.settings)
        context = ResearchContextBuilder(
            market_data=self.market_data,
            evidence=self.evidence,
            portfolio=broker,
            live_quotes=quotes,
        )
        return ResearchTeam(llm, context)

    @staticmethod
    def _intent(symbol: str, now: datetime, decision: FundDecision) -> TradeIntent:
        allocation = 0.0 if decision.action == Side.HOLD else decision.target_allocation_pct
        return TradeIntent(
            symbol=symbol.upper(),
            side=decision.action,
            product=Product.DELIVERY,
            thesis_id=f"fund:{symbol.upper()}:{int(now.timestamp())}",
            strategy_id="multi_agent_fund_v3_live_runtime",
            target_allocation_pct=allocation,
            entry_min=None,
            entry_max=None,
            stop_price=decision.stop_price,
            target_price=decision.target_price,
            confidence=decision.confidence,
            horizon=decision.horizon,
            evidence_ids=decision.evidence_ids,
            decision_at=now,
            data_cutoff_at=now,
        )

    def _persist_thesis(self, intent: TradeIntent, decision: FundDecision) -> None:
        if self.theses.get(intent.thesis_id) is not None:
            return
        self.theses.create(
            Thesis(
                thesis_id=intent.thesis_id,
                symbol=intent.symbol,
                strategy_id=intent.strategy_id,
                created_at=intent.decision_at,
                data_cutoff_at=intent.data_cutoff_at,
                horizon=intent.horizon,
                thesis=decision.thesis,
                evidence_ids=intent.evidence_ids,
            )
        )

    def _close_theses_if_flat(
        self,
        symbol: str,
        product: Product,
        broker: PortfolioBroker,
        now: datetime,
        reason: str,
    ) -> None:
        if any(
            position.symbol == symbol and position.product == product
            for position in broker.get_positions()
        ):
            return
        for thesis in self.theses.open_for_symbol(symbol):
            try:
                self.theses.close(thesis.thesis_id, now, reason)
            except ValueError:
                continue
        self.policies.clear(symbol, product)

    def _has_pending_live_order(self, symbol: str) -> bool:
        return any(record.symbol == symbol for record in self.live_ledger.pending())

    def _record_policy(self, intent: TradeIntent) -> None:
        if intent.side != Side.BUY:
            return
        self.policies.set(
            symbol=intent.symbol,
            product=intent.product,
            stop_price=intent.stop_price,
            target_price=intent.target_price,
            thesis_id=intent.thesis_id,
        )

    def _research_and_trade(
        self,
        *,
        symbol: str,
        mode: AppMode,
        broker: PortfolioBroker,
        api: ZerodhaApi,
        quotes: dict[str, Quote],
        now: datetime,
        new_buys_blocked: bool,
    ) -> None:
        try:
            fetched, inserted = self.news.ingest(symbol)
            self.operations.append_event(
                "evidence",
                "NEWS_REFRESHED",
                {"symbol": symbol, "fetched": fetched, "inserted": inserted},
                now,
            )
        except Exception as exc:
            self.operations.append_event(
                "evidence",
                "NEWS_REFRESH_FAILED",
                {"symbol": symbol, "error": type(exc).__name__},
                now,
            )

        try:
            team = self._build_team(broker, quotes)
            reports, fund_decision = team.run(symbol, now)
            intent = self._intent(symbol, now, fund_decision)
            manager_report = reports[-1] if reports else None
            self.operations.append_event(
                "ai",
                "FUND_DECISION",
                {
                    "symbol": symbol,
                    "mode": mode.value,
                    "action": intent.side.value,
                    "target_allocation_pct": intent.target_allocation_pct,
                    "confidence": intent.confidence,
                    "horizon": intent.horizon,
                    "thesis": fund_decision.thesis,
                    "evidence_ids": list(intent.evidence_ids),
                    "manager_summary": manager_report.summary if manager_report else "",
                },
                now,
            )
        except Exception as exc:
            self.operations.append_event(
                "ai",
                "RESEARCH_FAILED",
                {"symbol": symbol, "error": type(exc).__name__},
                now,
            )
            logger.exception("AI research failed for %s", symbol)
            self.state_store.record_decision(symbol, now)
            return

        self.state_store.record_decision(symbol, now)
        if intent.side == Side.HOLD:
            return
        if intent.side == Side.BUY and new_buys_blocked:
            self.operations.append_event(
                "risk",
                "REJECTED",
                {"symbol": symbol, "reason": "New buying is temporarily blocked"},
                now,
            )
            return
        if mode == AppMode.LIVE and self._has_pending_live_order(symbol):
            self.operations.append_event(
                "execution",
                "SKIPPED_PENDING_ORDER",
                {"symbol": symbol},
                now,
            )
            return

        fresh_quotes = api.quotes([symbol])
        quote = fresh_quotes.get(symbol)
        if quote is None:
            self.operations.append_event(
                "risk",
                "REJECTED",
                {"symbol": symbol, "reason": "Fresh quote unavailable"},
                now,
            )
            return

        decision_time = datetime.now(IST)
        portfolio, _ = self._valuation(broker, {**quotes, **fresh_quotes}, decision_time)
        risk_decision = self.risk.evaluate(intent, quote, portfolio, now=decision_time)
        self.operations.append_event(
            "risk",
            "APPROVED" if risk_decision.approved else "REJECTED",
            {
                "symbol": symbol,
                "mode": mode.value,
                "reason": risk_decision.reason,
                "daily_pnl": portfolio.daily_pnl,
                "equity": portfolio.equity,
            },
            decision_time,
        )
        if not risk_decision.approved or risk_decision.order_plan is None:
            return

        # Safe mode blocks exposure increases, not risk-reducing sells.
        if (
            mode == AppMode.LIVE
            and self.operations.get_safety_state().safe_mode
            and risk_decision.order_plan.side == Side.BUY
        ):
            self.operations.append_event(
                "execution",
                "BLOCKED_SAFE_MODE",
                {"symbol": symbol, "intent_id": risk_decision.order_plan.intent_id},
                decision_time,
            )
            return

        self._persist_thesis(intent, fund_decision)
        try:
            execution = broker.place_order(risk_decision.order_plan)
        except Exception as exc:
            self.operations.append_event(
                "execution",
                "ORDER_FAILED",
                {
                    "symbol": symbol,
                    "mode": mode.value,
                    "intent_id": risk_decision.order_plan.intent_id,
                    "error": type(exc).__name__,
                },
                decision_time,
            )
            logger.exception("order failed for %s", symbol)
            return

        self._record_policy(intent)
        self.operations.append_event(
            "execution",
            "ORDER_ACCEPTED",
            {
                "symbol": symbol,
                "mode": mode.value,
                "side": risk_decision.order_plan.side.value,
                "quantity": risk_decision.order_plan.quantity,
                "order_id": execution.order_id,
                "status": execution.status,
                "average_price": execution.average_price,
            },
            decision_time,
        )
        if mode == AppMode.PAPER and risk_decision.order_plan.side == Side.SELL:
            self._close_theses_if_flat(
                symbol,
                risk_decision.order_plan.product,
                broker,
                decision_time,
                "Position fully exited",
            )

    def _protective_exits(
        self,
        *,
        mode: AppMode,
        broker: PortfolioBroker,
        quotes: dict[str, Quote],
        now: datetime,
    ) -> None:
        for position in broker.get_positions():
            policy = self.policies.get(position.symbol, position.product)
            quote = quotes.get(position.symbol)
            if policy is None or quote is None:
                continue
            reason = ""
            if policy.stop_price is not None and quote.last_price <= policy.stop_price:
                reason = "STOP_LOSS"
            elif policy.target_price is not None and quote.last_price >= policy.target_price:
                reason = "TARGET_REACHED"
            if not reason:
                continue
            if mode == AppMode.LIVE and self._has_pending_live_order(position.symbol):
                continue
            intent = TradeIntent(
                symbol=position.symbol,
                side=Side.SELL,
                product=position.product,
                thesis_id=policy.thesis_id,
                strategy_id="deterministic_protective_exit",
                target_allocation_pct=0,
                confidence=1.0,
                horizon="immediate protective exit",
                evidence_ids=(),
                decision_at=now,
                data_cutoff_at=now,
            )
            portfolio, _ = self._valuation(broker, quotes, now)
            risk_decision = self.risk.evaluate(intent, quote, portfolio, now=now)
            if not risk_decision.approved or risk_decision.order_plan is None:
                continue
            plan = risk_decision.order_plan.model_copy(
                update={
                    "intent_id": (
                        f"protective:{position.symbol}:{reason}:{int(now.timestamp())}"
                    )
                }
            )
            try:
                execution = broker.place_order(plan)
            except Exception as exc:
                self.operations.append_event(
                    "execution",
                    "PROTECTIVE_EXIT_FAILED",
                    {
                        "symbol": position.symbol,
                        "reason": reason,
                        "error": type(exc).__name__,
                    },
                    now,
                )
                continue
            self.operations.append_event(
                "execution",
                "PROTECTIVE_EXIT",
                {
                    "symbol": position.symbol,
                    "reason": reason,
                    "quantity": plan.quantity,
                    "order_id": execution.order_id,
                    "status": execution.status,
                },
                now,
            )
            if mode == AppMode.PAPER:
                self._close_theses_if_flat(
                    position.symbol,
                    position.product,
                    broker,
                    now,
                    reason,
                )

    def _reconcile_live(self, broker: ManagedLiveBroker, now: datetime) -> None:
        uncertain = [
            record
            for record in self.live_ledger.pending()
            if not record.broker_order_id and record.status in {"UNKNOWN", "PENDING_SEND"}
        ]
        if uncertain:
            state = self.operations.get_safety_state()
            if not state.safe_mode:
                self.operations.set_safe_mode(
                    True,
                    "UNCERTAIN_LIVE_ORDER_REQUIRES_RECONCILIATION",
                    now,
                )
            return
        try:
            updates = broker.reconcile(now)
        except Exception:
            logger.exception("live order reconciliation failed")
            return
        for intent_id, status in updates:
            self.operations.append_event(
                "execution",
                "LIVE_ORDER_RECONCILED",
                {"intent_id": intent_id, "status": status},
                now,
            )
        positions = broker.get_positions()
        pending = self.live_ledger.pending()
        for policy in self.policies.all():
            has_position = any(
                position.symbol == policy.symbol and position.product == policy.product
                for position in positions
            )
            has_pending_buy = any(
                record.symbol == policy.symbol
                and record.product == policy.product
                and record.side == Side.BUY
                for record in pending
            )
            if not has_position and not has_pending_buy:
                self._close_theses_if_flat(
                    policy.symbol,
                    policy.product,
                    broker,
                    now,
                    "Live position fully exited or entry did not fill",
                )

    def tick(self, now: datetime | None = None) -> None:
        current = now or datetime.now(IST)
        if current.tzinfo is None:
            raise ValueError("runtime tick time must be timezone-aware")
        mode = self.mode_store.load().mode
        if mode != self._last_mode:
            self.operations.append_event(
                "runtime",
                "MODE_ACTIVE",
                {"mode": mode.value},
                current,
            )
            logger.warning("runtime mode is now %s", mode.value)
            self._last_mode = mode

        api = self._api()
        if api is None:
            return
        try:
            self._warm_history(api, current)
        except Exception:
            logger.exception("market history warm-up failed")

        if mode == AppMode.LIVE:
            broker: PortfolioBroker = self._live_broker(api)
            self._reconcile_live(broker, current)
        else:
            broker = self.paper_broker

        positions = broker.get_positions()
        try:
            quotes = self._quotes_for_portfolio(api, positions)
        except Exception:
            logger.exception("live quote refresh failed")
            return
        if not quotes:
            return

        portfolio, dashboard_snapshot = self._valuation(broker, quotes, current)
        self._write_nav(dashboard_snapshot, current)
        phase = self.calendar.phase_at(current)
        if phase != MarketPhase.OPEN:
            return

        # Stops/targets are deterministic and continue even if new buying is blocked.
        self._protective_exits(
            mode=mode,
            broker=broker,
            quotes=quotes,
            now=current,
        )

        daily_loss_active = portfolio.daily_pnl <= -(
            portfolio.equity * self.settings.max_daily_loss_pct
        )
        safe_mode = mode == AppMode.LIVE and self.operations.get_safety_state().safe_mode
        if daily_loss_active:
            self.operations.append_event(
                "risk",
                "DAILY_LOSS_LIMIT_ACTIVE",
                {"daily_pnl": portfolio.daily_pnl, "equity": portfolio.equity},
                current,
            )

        # When risk brakes are active, only held symbols are researched so AI can reduce risk.
        candidates = self._candidates(
            broker.get_positions(),
            current,
            allow_new_buys=not daily_loss_active and not safe_mode,
        )
        for symbol in candidates:
            if symbol not in quotes or not self._decision_due(symbol, current):
                continue
            self._research_and_trade(
                symbol=symbol,
                mode=mode,
                broker=broker,
                api=api,
                quotes=quotes,
                now=current,
                new_buys_blocked=daily_loss_active or safe_mode,
            )
