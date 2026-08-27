from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from statistics import mean

from app.market_data import HistoricalDataStore
from app.nse_sources import NSEInstrumentSource


@dataclass(frozen=True)
class UniverseRules:
    candidate_limit: int = 75
    min_price: float = 20.0
    min_history_bars: int = 20
    min_avg_traded_value: float = 50_000_000.0


@dataclass(frozen=True)
class UniverseCandidate:
    symbol: str
    last_price: float
    avg_traded_value: float
    momentum_20: float
    score: float


class DynamicNSEUniverse:
    """Discovers NSE EQ symbols then deterministically screens/ranks them.

    Paper and live modes use this exact selector. A non-empty explicit override
    deliberately constrains the mandate; otherwise the official NSE EQ master is
    the source of truth. Selection is point-in-time and never reads future candles.
    """

    def __init__(
        self,
        market_data: HistoricalDataStore,
        rules: UniverseRules,
        explicit_override: tuple[str, ...] = (),
        source: NSEInstrumentSource | None = None,
    ) -> None:
        self.market_data = market_data
        self.rules = rules
        self.explicit_override = tuple(symbol.upper() for symbol in explicit_override)
        self.source = source or NSEInstrumentSource()

    def _symbols(self) -> list[str]:
        if self.explicit_override:
            return sorted(set(self.explicit_override))
        master = self.source.fetch()
        return sorted({instrument.symbol for instrument in master.all()})

    def select(self, as_of: datetime) -> list[UniverseCandidate]:
        if as_of.tzinfo is None:
            raise ValueError("universe selection time must be timezone-aware")
        candidates: list[UniverseCandidate] = []
        for symbol in self._symbols():
            history = self.market_data.as_of(symbol, cutoff=as_of, limit=60)
            if len(history) < self.rules.min_history_bars:
                continue
            window = history[-20:]
            last = window[-1]
            if last.close < self.rules.min_price:
                continue
            avg_traded_value = mean(item.close * item.volume for item in window)
            if avg_traded_value < self.rules.min_avg_traded_value:
                continue
            first_close = window[0].close
            momentum_20 = (last.close / first_close) - 1 if first_close > 0 else 0.0
            score = avg_traded_value * (1.0 + max(-0.5, min(0.5, momentum_20)))
            candidates.append(
                UniverseCandidate(
                    symbol=symbol,
                    last_price=last.close,
                    avg_traded_value=avg_traded_value,
                    momentum_20=momentum_20,
                    score=score,
                )
            )
        candidates.sort(key=lambda item: item.score, reverse=True)
        return candidates[: self.rules.candidate_limit]
