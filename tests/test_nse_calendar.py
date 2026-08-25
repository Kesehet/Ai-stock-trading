from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.nse_calendar import nse_capital_market_calendar
from app.scheduler import MarketPhase

IST = ZoneInfo("Asia/Kolkata")


def test_verified_2026_capital_market_holiday_is_closed() -> None:
    holiday = datetime(2026, 9, 14, 10, 0, tzinfo=IST)
    calendar = nse_capital_market_calendar(holiday)

    assert calendar.phase_at(holiday) == MarketPhase.CLOSED


def test_normal_2026_weekday_is_open_during_session() -> None:
    trading_day = datetime(2026, 8, 25, 10, 0, tzinfo=IST)
    calendar = nse_capital_market_calendar(trading_day)

    assert calendar.phase_at(trading_day) == MarketPhase.OPEN


def test_unknown_calendar_year_fails_closed() -> None:
    unknown_year = datetime(2027, 1, 4, 10, 0, tzinfo=IST)

    with pytest.raises(RuntimeError, match="not verified for 2027"):
        nse_capital_market_calendar(unknown_year)
