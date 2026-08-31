from __future__ import annotations

from datetime import datetime

from app.config import AppMode
from app.models import Position, Quote
from app.production_trader import ProductionAutonomousTrader
from app.autonomous_trader import PortfolioBroker


class HardenedProductionAutonomousTrader(ProductionAutonomousTrader):
    """Production trader with execution-basis safeguards shared by paper and live modes."""

    @staticmethod
    def _target_is_profitable(position: Position, target_price: float | None) -> bool:
        """A profit target must be strictly above the actual managed cost basis."""
        return target_price is not None and target_price > position.average_price

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
