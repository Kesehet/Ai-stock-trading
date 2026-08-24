from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.scheduler import MarketCalendar, MarketPhase

IST = ZoneInfo("Asia/Kolkata")


def _at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 8, 25, hour, minute, tzinfo=IST)


def test_market_day_phases() -> None:
    calendar = MarketCalendar()

    assert calendar.phase_at(_at(8, 30)) == MarketPhase.PREMARKET
    assert calendar.phase_at(_at(9, 15)) == MarketPhase.OPEN
    assert calendar.phase_at(_at(15, 20)) == MarketPhase.CLOSING
    assert calendar.phase_at(_at(16, 0)) == MarketPhase.POSTMARKET
    assert calendar.phase_at(_at(18, 0)) == MarketPhase.CLOSED


def test_exchange_holiday_is_closed() -> None:
    calendar = MarketCalendar(holidays={date(2026, 8, 25)})

    assert calendar.phase_at(_at(10, 0)) == MarketPhase.CLOSED


def test_weekend_is_closed() -> None:
    saturday = datetime(2026, 8, 29, 10, 0, tzinfo=IST)

    assert MarketCalendar().phase_at(saturday) == MarketPhase.CLOSED
