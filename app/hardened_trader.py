from __future__ import annotations

from datetime import datetime, time, timedelta

from app.autonomous_trader import PortfolioBroker
from app.config import AppMode, Settings
from app.costs import ZERODHA_NSE_CASH_2026
from app.dashboard_store import PortfolioSnapshot as DashboardSnapshot
from app.models import Position, Product, Quote, Side, TradeIntent
from app.production_trader import ProductionAutonomousTrader
from app.research_team import FundDecision
from app.risk import PortfolioSnapshot
from app.scheduler import IST
from app.stock_memory import StockMemoryStore


class HardenedProductionAutonomousTrader(ProductionAutonomousTrader):
    """Production trader with execution-basis safeguards shared by paper and live modes."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self._decision_memory = StockMemoryStore(self.data_dir / "stock-memory.sqlite3")
        self._latest_portfolio: PortfolioSnapshot | None = None
        self._latest_quotes: dict[str, Quote] = {}
        self._unexecutable_skip_until: dict[str, datetime] = {}

    @staticmethod
    def _target_is_profitable(position: Position, target_price: float | None) -> bool:
        """A profit target must be strictly above the actual managed cost basis."""
        return target_price is not None and target_price > position.average_price

    @staticmethod
    def _requires_controlled_pullback(
        *,
        move_pct: float,
        breakout_pct: float,
        intraday_position: float,
    ) -> bool:
        """Identify fresh momentum entries whose location is vulnerable to exhaustion.

        This is intentionally narrower than a momentum veto. A strong stock can still be
        researched and bought; the system only refuses to pay near the top of the current
        range after a material same-day extension. The 6%/78% boundary captures the two
        repeated immediate-adverse examples observed in the ₹500 experiment while leaving
        ordinary trend continuation untouched. A 10%+ breakout remains independently
        overextended regardless of the day's range position.
        """
        return breakout_pct >= 0.10 or (
            move_pct >= 0.06 and intraday_position >= 0.78
        )

    @staticmethod
    def _controlled_pullback_entry_max(
        *,
        price: float,
        low_price: float,
        high_price: float,
        existing_entry_max: float | None,
    ) -> float:
        """Require a meaningful retracement instead of a token one-tick pullback."""
        day_range = max(0.0, high_price - low_price)
        pullback_level = (
            low_price + (0.70 * day_range)
            if day_range > 0
            else price * 0.985
        )
        candidate = min(pullback_level, price * 0.99)
        return candidate if existing_entry_max is None else min(existing_entry_max, candidate)

    def _intent(  # type: ignore[override]
        self,
        symbol: str,
        now: datetime,
        decision: FundDecision,
    ) -> TradeIntent:
        intent = super()._intent(symbol, now, decision)
        if intent.side != Side.BUY:
            return intent

        normalized = symbol.upper()
        portfolio = self._latest_portfolio
        if portfolio is not None and any(
            position.symbol == normalized for position in portfolio.positions
        ):
            return intent

        with self._intraday_state_lock:
            snapshot = self._intraday_snapshots.get(normalized)
        if snapshot is None or snapshot.last_price <= 0:
            return intent

        price = snapshot.last_price
        day_range = max(0.0, snapshot.high_price - snapshot.low_price)
        move_pct = (
            (price / snapshot.previous_close) - 1.0
            if snapshot.previous_close > 0
            else 0.0
        )
        intraday_position = (
            (price - snapshot.low_price) / day_range if day_range > 0 else 0.5
        )
        history = self.market_data.as_of(normalized, now, limit=20)
        recent_high = max((candle.high for candle in history), default=price)
        breakout_pct = (price / recent_high) - 1.0 if recent_high > 0 else 0.0

        if not self._requires_controlled_pullback(
            move_pct=move_pct,
            breakout_pct=breakout_pct,
            intraday_position=intraday_position,
        ):
            return intent

        tightened_entry_max = self._controlled_pullback_entry_max(
            price=price,
            low_price=snapshot.low_price,
            high_price=snapshot.high_price,
            existing_entry_max=intent.entry_max,
        )
        if intent.entry_max is not None and tightened_entry_max >= intent.entry_max:
            return intent

        self.operations.append_event(
            "risk",
            "ENTRY_PULLBACK_TIGHTENED",
            {
                "symbol": normalized,
                "last_price": price,
                "entry_max": tightened_entry_max,
                "move_pct": move_pct,
                "breakout_pct": breakout_pct,
                "intraday_position": intraday_position,
                "reason": (
                    "Fresh momentum entry is materially extended near the top of the "
                    "intraday range; wait for a controlled pullback"
                ),
            },
            now,
        )
        return intent.model_copy(update={"entry_max": tightened_entry_max})

    def _valuation(
        self,
        broker: PortfolioBroker,
        quotes: dict[str, Quote],
        now: datetime,
    ) -> tuple[PortfolioSnapshot, DashboardSnapshot]:
        """Cache the same managed portfolio/quotes used by risk for pre-research checks."""
        result = super()._valuation(broker, quotes, now)
        self._latest_portfolio = result[0]
        self._latest_quotes = dict(quotes)
        return result

    @staticmethod
    def _fresh_entry_block_reason(
        symbol: str,
        quote: Quote,
        portfolio: PortfolioSnapshot,
        *,
        max_position_pct: float,
        max_open_positions: int,
    ) -> str:
        """Return a hard reason when no legal one-share fresh position can exist."""
        normalized = symbol.upper()
        if any(position.symbol == normalized for position in portfolio.positions):
            return ""
        if portfolio.open_positions >= max_open_positions:
            return "Maximum open positions reached"

        one_share_budget = max(
            0.0,
            min(portfolio.cash, portfolio.equity * max_position_pct),
        )
        if quote.last_price > one_share_budget:
            return "One share exceeds available cash or maximum position budget"
        return ""

    def _has_managed_policy(self, symbol: str) -> bool:
        return any(
            self.policies.get(symbol, product) is not None
            for product in (Product.DELIVERY, Product.INTRADAY)
        )

    @staticmethod
    def _flat_symbol_cooldown_seconds(action: str, base_seconds: int) -> int:
        """Slow repeated deep research when the latest decision had no executable position."""
        base = max(1, base_seconds)
        normalized = action.upper()
        if normalized == Side.SELL.value:
            return base * 4
        if normalized == Side.HOLD.value:
            return base * 2
        return base

    def _decision_due(self, symbol: str, now: datetime) -> bool:
        if not super()._decision_due(symbol, now):
            return False

        normalized = symbol.upper()
        portfolio = self._latest_portfolio
        quote = self._latest_quotes.get(normalized)
        if portfolio is not None and quote is not None:
            block_reason = self._fresh_entry_block_reason(
                normalized,
                quote,
                portfolio,
                max_position_pct=self.settings.max_position_pct,
                max_open_positions=self.settings.max_open_positions,
            )
            if block_reason:
                until = self._unexecutable_skip_until.get(normalized)
                if until is None or now >= until:
                    one_share_budget = max(
                        0.0,
                        min(
                            portfolio.cash,
                            portfolio.equity * self.settings.max_position_pct,
                        ),
                    )
                    self.operations.append_event(
                        "research",
                        "RESEARCH_SKIPPED_UNEXECUTABLE",
                        {
                            "symbol": normalized,
                            "reason": block_reason,
                            "last_price": quote.last_price,
                            "available_cash": portfolio.cash,
                            "equity": portfolio.equity,
                            "one_share_budget": one_share_budget,
                            "open_positions": portfolio.open_positions,
                            "max_open_positions": self.settings.max_open_positions,
                            "max_position_pct": self.settings.max_position_pct,
                        },
                        now,
                    )
                    self._unexecutable_skip_until[normalized] = now + timedelta(
                        seconds=max(1, self.settings.decision_interval_seconds)
                    )
                return False

        if self._has_managed_policy(normalized):
            return True

        latest = self._decision_memory.recent_for_symbol(normalized, limit=1)
        if not latest:
            return True
        cooldown = self._flat_symbol_cooldown_seconds(
            latest[0].action,
            self.settings.decision_interval_seconds,
        )
        elapsed = (now - latest[0].recorded_at).total_seconds()
        return elapsed >= cooldown

    @staticmethod
    def _overnight_cost_metrics(
        position: Position,
        quote: Quote,
        *,
        stop_price: float,
        target_price: float,
    ) -> tuple[float, float, float, float]:
        """Return carry reward, carry downside, cost-adjusted RR and future target exit cost."""
        quantity = position.quantity
        current_turnover = quote.last_price * quantity
        target_turnover = target_price * quantity
        stop_turnover = stop_price * quantity

        exit_now_cost = ZERODHA_NSE_CASH_2026.charges(
            turnover=current_turnover,
            side=Side.SELL,
            product=Product.INTRADAY,
        )
        target_exit_cost = ZERODHA_NSE_CASH_2026.charges(
            turnover=target_turnover,
            side=Side.SELL,
            product=Product.DELIVERY,
            include_dp=True,
        )
        stop_exit_cost = ZERODHA_NSE_CASH_2026.charges(
            turnover=stop_turnover,
            side=Side.SELL,
            product=Product.DELIVERY,
            include_dp=True,
        )

        reward = (
            (target_price - quote.last_price) * quantity
            - (target_exit_cost - exit_now_cost)
        )
        downside = (
            (quote.last_price - stop_price) * quantity
            + (stop_exit_cost - exit_now_cost)
        )
        reward_risk = reward / downside if downside > 0 else 0.0
        return reward, downside, reward_risk, target_exit_cost

    def _overnight_cost_exits(
        self,
        *,
        mode: AppMode,
        broker: PortfolioBroker,
        quotes: dict[str, Quote],
        now: datetime,
    ) -> None:
        current_ist = now.astimezone(IST)
        if current_ist.time() < time(15, 15):
            return

        for position in broker.get_positions():
            if position.product != Product.DELIVERY:
                continue
            policy = self.policies.get(position.symbol, position.product)
            quote = quotes.get(position.symbol)
            if policy is None or quote is None:
                continue
            if policy.updated_at.astimezone(IST).date() != current_ist.date():
                continue
            if policy.stop_price is None or policy.target_price is None:
                continue
            if not (0 < policy.stop_price < quote.last_price < policy.target_price):
                continue

            reward, downside, reward_risk, target_exit_cost = self._overnight_cost_metrics(
                position,
                quote,
                stop_price=policy.stop_price,
                target_price=policy.target_price,
            )
            if reward > 0 and reward_risk >= self.risk.limits.min_reward_risk:
                continue
            if mode == AppMode.LIVE and self._has_pending_live_order(position.symbol):
                continue

            intent = TradeIntent(
                symbol=position.symbol,
                side=Side.SELL,
                product=position.product,
                thesis_id=policy.thesis_id,
                strategy_id="deterministic_overnight_cost_gate",
                target_allocation_pct=0,
                confidence=1.0,
                horizon="same-day exit before uneconomic overnight carry",
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
                        f"overnight-cost:{position.symbol}:{current_ist.date().isoformat()}"
                    )
                }
            )
            try:
                execution = broker.place_order(plan)
            except Exception as exc:
                self.operations.append_event(
                    "execution",
                    "OVERNIGHT_COST_EXIT_FAILED",
                    {
                        "symbol": position.symbol,
                        "error": type(exc).__name__,
                    },
                    now,
                )
                continue

            self.operations.append_event(
                "execution",
                "OVERNIGHT_COST_EXIT",
                {
                    "symbol": position.symbol,
                    "mode": mode.value,
                    "quantity": plan.quantity,
                    "current_price": quote.last_price,
                    "target_price": policy.target_price,
                    "stop_price": policy.stop_price,
                    "expected_carry_reward_after_costs": round(reward, 4),
                    "expected_carry_downside_after_costs": round(downside, 4),
                    "cost_adjusted_reward_risk": round(reward_risk, 4),
                    "estimated_future_delivery_exit_cost": round(target_exit_cost, 4),
                    "minimum_reward_risk": self.risk.limits.min_reward_risk,
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
                    "Overnight carry rejected by cost-adjusted economics",
                )

    def _protective_exits(
        self,
        *,
        mode: AppMode,
        broker: PortfolioBroker,
        quotes: dict[str, Quote],
        now: datetime,
    ) -> None:
        # AI stop/target levels are chosen before execution. Slippage, partial fills,
        # or later averaging can move the managed position basis beyond the stored
        # target. Disable such a target before the deterministic exit engine sees it;
        # otherwise a nominal TARGET_REACHED can realize a loss immediately after entry.
        for position in broker.get_positions():
            policy = self.policies.get(position.symbol, position.product)
            if policy is None or policy.target_price is None:
                continue
            if self._target_is_profitable(position, policy.target_price):
                continue

            invalid_target = policy.target_price
            self.policies.set(
                symbol=policy.symbol,
                product=policy.product,
                stop_price=policy.stop_price,
                target_price=None,
                thesis_id=policy.thesis_id,
            )
            self.operations.append_event(
                "risk",
                "PROTECTIVE_TARGET_DISABLED",
                {
                    "symbol": position.symbol,
                    "mode": mode.value,
                    "target_price": invalid_target,
                    "position_average_price": position.average_price,
                    "reason": "Target does not clear actual managed position cost basis",
                },
                now,
            )

        super()._protective_exits(
            mode=mode,
            broker=broker,
            quotes=quotes,
            now=now,
        )
        self._overnight_cost_exits(
            mode=mode,
            broker=broker,
            quotes=quotes,
            now=now,
        )
