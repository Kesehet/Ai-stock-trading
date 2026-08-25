from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class FundamentalSnapshot:
    symbol: str
    available_at: datetime
    revenue: float | None = None
    net_income: float | None = None
    equity: float | None = None
    debt: float | None = None
    operating_cash_flow: float | None = None
    shares_outstanding: float | None = None
    market_cap: float | None = None
    prior_revenue: float | None = None
    prior_net_income: float | None = None

    def ratios(self) -> dict[str, float | None]:
        revenue_growth = None
        if (
            self.revenue is not None
            and self.prior_revenue is not None
            and self.prior_revenue != 0
        ):
            revenue_growth = (self.revenue / self.prior_revenue) - 1
        profit_growth = None
        if (
            self.net_income is not None
            and self.prior_net_income is not None
            and self.prior_net_income != 0
        ):
            profit_growth = (self.net_income / self.prior_net_income) - 1
        net_margin = None
        if self.net_income is not None and self.revenue is not None and self.revenue != 0:
            net_margin = self.net_income / self.revenue
        roe = None
        if self.net_income is not None and self.equity is not None and self.equity != 0:
            roe = self.net_income / self.equity
        debt_to_equity = None
        if self.debt is not None and self.equity is not None and self.equity != 0:
            debt_to_equity = self.debt / self.equity
        price_to_earnings = None
        if (
            self.market_cap is not None
            and self.net_income is not None
            and self.net_income != 0
        ):
            price_to_earnings = self.market_cap / self.net_income
        return {
            "revenue_growth": revenue_growth,
            "profit_growth": profit_growth,
            "net_margin": net_margin,
            "roe": roe,
            "debt_to_equity": debt_to_equity,
            "price_to_earnings": price_to_earnings,
        }

    def as_text(self) -> str:
        ratios = self.ratios()
        lines = [f"available_at={self.available_at.isoformat()}"]
        for key, value in ratios.items():
            lines.append(f"{key}={value:.4f}" if value is not None else f"{key}=NA")
        if self.operating_cash_flow is not None:
            lines.append(f"operating_cash_flow={self.operating_cash_flow:.2f}")
        return "\n".join(lines)


class FundamentalStore:
    def __init__(self, snapshots: list[FundamentalSnapshot] | None = None) -> None:
        self._items: dict[str, list[FundamentalSnapshot]] = {}
        for snapshot in snapshots or []:
            self.add(snapshot)

    def add(self, snapshot: FundamentalSnapshot) -> None:
        if snapshot.available_at.tzinfo is None:
            raise ValueError("fundamental available_at must be timezone-aware")
        items = self._items.setdefault(snapshot.symbol.upper(), [])
        items.append(snapshot)
        items.sort(key=lambda item: item.available_at)

    def latest_as_of(self, symbol: str, cutoff: datetime) -> FundamentalSnapshot | None:
        visible = [
            item
            for item in self._items.get(symbol.upper(), [])
            if item.available_at <= cutoff
        ]
        return visible[-1] if visible else None
