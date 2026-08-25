from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from enum import StrEnum
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


class MarketPhase(StrEnum):
    CLOSED = "closed"
    PREMARKET = "premarket"
    OPEN = "open"
    CLOSING = "closing"
    POSTMARKET = "postmarket"


@dataclass(frozen=True)
class MarketSchedule:
    premarket_start: time = time(8, 0)
    market_open: time = time(9, 15)
    closing_start: time = time(15, 15)
    market_close: time = time(15, 30)
    postmarket_end: time = time(17, 30)


class MarketCalendar:
    """Trading-day/phase resolver.

    Holiday dates are injected from an exchange calendar source. Weekends are always closed.
    """

    def __init__(
        self,
        holidays: set[date] | None = None,
        schedule: MarketSchedule | None = None,
    ) -> None:
        self.holidays = holidays or set()
        self.schedule = schedule or MarketSchedule()

    def is_trading_day(self, value: date) -> bool:
        return value.weekday() < 5 and value not in self.holidays

    def phase_at(self, value: datetime) -> MarketPhase:
        if value.tzinfo is None:
            raise ValueError("scheduler time must be timezone-aware")
        local = value.astimezone(IST)
        if not self.is_trading_day(local.date()):
            return MarketPhase.CLOSED
        current = local.time().replace(tzinfo=None)
        schedule = self.schedule
        if schedule.premarket_start <= current < schedule.market_open:
            return MarketPhase.PREMARKET
        if schedule.market_open <= current < schedule.closing_start:
            return MarketPhase.OPEN
        if schedule.closing_start <= current < schedule.market_close:
            return MarketPhase.CLOSING
        if schedule.market_close <= current < schedule.postmarket_end:
            return MarketPhase.POSTMARKET
        return MarketPhase.CLOSED
