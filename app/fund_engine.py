from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from app.ai import OllamaClient
from app.brokers import Broker
from app.evidence.store import EvidenceStore
from app.history_loader import NSEHistoryLoader
from app.market_data import HistoricalDataStore
from app.models import Product, Side, TradeIntent
from app.operations import OperationsStore
from app.research_team import ResearchContextBuilder, ResearchTeam
from app.risk import PortfolioSnapshot, RiskEngine, RiskLimits
from app.strategies import MomentumStrategy
from app.universe import DynamicNSEUniverse, UniverseRules
from app.zerodha_market import QuoteProvider

logger = logging.getLogger("ai-stock-trading.fund-engine")


@dataclass(frozen=True)
class FundCycleResult:
    discovered: int
    considered: int
    orders: int
    holds: int
    rejected: int
    errors: int


class AutonomousFundEngine:
    """Broker-agnostic autonomous Indian cash-equity fund loop.

    Paper and live modes intentionally share this exact class. The only execution
    difference is the injected Broker implementation. Market data, universe
    discovery, research, risk, scheduling inputs, and audit behavior are identical.
    """

    def __init__(
        self,
        *,
        data_dir: str | Path,
        broker: Broker,
        quote_provider: QuoteProvider,
        operations: OperationsStore,
        explicit_universe: tuple[str, ...],
        universe_rules: UniverseRules,
        ollama_base_url: str,
        ollama_model: str,
        max_position_pct: float,
        max_daily_loss_pct: float,
        max_open_positions: int,
        history_days: int = 90,
        fallback_momentum: bool = True,
        fallback_target_pct: float = 0.03,
        audit_category: str = "fund",
    ) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.broker = broker
        self.quote_provider = quote_provider
        self.operations = operations
        self.history_days = history_days
        self.fallback_momentum = fallback_momentum
        self.fallback_target_pct = fallback_target_pct
        self.audit_category = audit_category
        self.risk = RiskEngine(
            RiskLimits(
                max_position_pct=max_position_pct,
                max_daily_loss_pct=max_daily_loss_pct,
                max_open_positions=max_open_positions,
            )
        )
        self.market_data = HistoricalDataStore()
        self.history_loader = NSEHistoryLoader(self.data_dir / "nse-history")
        self.evidence = EvidenceStore(self.data_dir / "evidence.sqlite3")
        self.universe = DynamicNSEUniverse(
            self.market_data,
            universe_rules,
            explicit_override=explicit_universe,
        )
        llm = OllamaClient(ollama_base_url, ollama_model)
        context = ResearchContextBuilder(
            market_data=self.market_data,
            evidence=self.evidence,
            portfolio=self.broker,
        )
        self.research = ResearchTeam(llm, context)
        self.momentum = MomentumStrategy(lookback=20, target_weight=fallback_target_pct)
        self._history_loaded_through: date | None = None

    def _event(self, action: str, payload: dict[str, object]) -> None:
        self.operations.append_event(self.audit_category, action, payload)

    def _refresh_history(self, today: date) -> None:
        end = today - timedelta(days=1)
        if self._history_loaded_through == end:
            return
        start = end - timedelta(days=self.history_days)
        self.market_data, result = self.history_loader.load_range(
            start,
            end,
            store=self.market_data,
        )
        self._history_loaded_through = end
        self._event(
            "HISTORY_REFRESHED",
            {
                "start": start.isoformat(),
                "end": end.isoformat(),
                "loaded_days": result.loaded_days,
                "missing_days": result.missing_days,
                "candles": result.candles,
            },
        )

    def _equity(self) -> float:
        equity = self.broker.get_cash()
        for position in self.broker.get_positions():
            try:
                quote = self.quote_provider.get_quote(position.symbol)
                equity += position.quantity * quote.last_price
            except Exception:
                equity += position.quantity * position.average_price
        return equity

    def _portfolio(self) -> PortfolioSnapshot:
        return PortfolioSnapshot(
            cash=self.broker.get_cash(),
            equity=self._equity(),
            open_positions=len(self.broker.get_positions()),
            daily_pnl=0.0,
        )

    def _fallback_intent(self, symbol: str, now: datetime) -> TradeIntent:
        history = self.market_data.as_of(symbol, now, limit=60)
        signal = self.momentum.generate(symbol, history)
        if signal.target_weight <= 0:
            side = Side.HOLD
            allocation = 0.0
        else:
            side = Side.BUY
            allocation = min(signal.target_weight, self.fallback_target_pct)
        self._event(
            "AI_FALLBACK_USED",
            {"symbol": symbol, "reason": signal.reason, "side": side.value},
        )
        return TradeIntent(
            symbol=symbol,
            side=side,
            product=Product.DELIVERY,
            thesis_id=f"fallback:{symbol}:{int(now.timestamp())}",
            strategy_id="momentum_fallback_v1",
            target_allocation_pct=allocation,
            confidence=0.5,
            horizon="5-20 trading days",
            evidence_ids=(),
            decision_at=now,
            data_cutoff_at=now,
        )

    def run_cycle(self, now: datetime | None = None) -> FundCycleResult:
        decision_time = now or datetime.now(UTC)
        if decision_time.tzinfo is None:
            raise ValueError("fund cycle time must be timezone-aware")
        self._refresh_history(decision_time.date())
        selected = self.universe.select(decision_time)
        symbols = [candidate.symbol for candidate in selected]
        held = {position.symbol for position in self.broker.get_positions()}
        orders = holds = rejected = errors = 0

        self._event(
            "CYCLE_STARTED",
            {
                "candidate_count": len(symbols),
                "candidates": symbols,
                "cash": self.broker.get_cash(),
                "equity": self._equity(),
            },
        )

        for symbol in symbols:
            if symbol in held:
                holds += 1
                self._event("SKIPPED_ALREADY_HELD", {"symbol": symbol})
                continue
            try:
                try:
                    intent = self.research.trade_intent(symbol, decision_time)
                except Exception as exc:
                    if not self.fallback_momentum:
                        raise
                    logger.warning("AI research failed for %s: %s", symbol, exc)
                    self._event(
                        "AI_RESEARCH_FAILED",
                        {"symbol": symbol, "error": type(exc).__name__},
                    )
                    intent = self._fallback_intent(symbol, decision_time)

                self._event(
                    "INTENT",
                    {
                        "symbol": symbol,
                        "side": intent.side.value,
                        "allocation": intent.target_allocation_pct,
                        "confidence": intent.confidence,
                        "strategy": intent.strategy_id,
                    },
                )
                if intent.side == Side.HOLD:
                    holds += 1
                    continue

                quote = self.quote_provider.get_quote(symbol)
                decision = self.risk.evaluate(intent, quote, self._portfolio(), now=quote.as_of)
                if not decision.approved or decision.order_plan is None:
                    rejected += 1
                    self._event(
                        "RISK_REJECTED",
                        {"symbol": symbol, "reason": decision.reason},
                    )
                    continue

                execution = self.broker.place_order(decision.order_plan)
                orders += 1
                held.add(symbol)
                self._event(
                    "ORDER_FILLED",
                    {
                        "symbol": symbol,
                        "order_id": execution.order_id,
                        "quantity": execution.filled_quantity,
                        "price": execution.average_price,
                        "cash_after": self.broker.get_cash(),
                    },
                )
            except Exception as exc:
                errors += 1
                logger.exception("fund cycle failed for %s", symbol)
                self._event(
                    "SYMBOL_ERROR",
                    {"symbol": symbol, "error": type(exc).__name__, "message": str(exc)[:300]},
                )

        result = FundCycleResult(
            discovered=len(self.market_data.symbols()),
            considered=len(symbols),
            orders=orders,
            holds=holds,
            rejected=rejected,
            errors=errors,
        )
        self._event(
            "CYCLE_COMPLETED",
            {
                "discovered": result.discovered,
                "considered": result.considered,
                "orders": result.orders,
                "holds": result.holds,
                "rejected": result.rejected,
                "errors": result.errors,
                "cash": self.broker.get_cash(),
                "equity": self._equity(),
            },
        )
        return result
