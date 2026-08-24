from __future__ import annotations

from datetime import date, datetime

from app.scheduler import IST, MarketCalendar

NSE_2026_CAPITAL_MARKET_CIRCULAR = "NSE/CMTR/71775"

_NSE_CAPITAL_MARKET_HOLIDAYS: dict[int, frozenset[date]] = {
    2026: frozenset(
        {
            date(2026, 1, 26),
            date(2026, 3, 3),
            date(2026, 3, 26),
            date(2026, 3, 31),
            date(2026, 4, 3),
            date(2026, 4, 14),
            date(2026, 5, 1),
            date(2026, 5, 28),
            date(2026, 6, 26),
            date(2026, 9, 14),
            date(2026, 10, 2),
            date(2026, 10, 20),
            date(2026, 11, 10),
            date(2026, 11, 24),
            date(2026, 12, 25),
        }
    )
}


def nse_capital_market_calendar(as_of: datetime | None = None) -> MarketCalendar:
    current = (as_of or datetime.now(IST)).astimezone(IST)
    holidays = _NSE_CAPITAL_MARKET_HOLIDAYS.get(current.year)
    if holidays is None:
        raise RuntimeError(
            f"NSE capital-market holiday calendar is not verified for {current.year}; "
            "refusing to assume trading availability"
        )
    return MarketCalendar(holidays=set(holidays))
