from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.models import Product, Side


@dataclass(frozen=True)
class EquityChargeSchedule:
    name: str
    effective_from: date
    exchange_transaction_rate: float
    sebi_rate: float
    gst_rate: float
    delivery_stt_rate: float
    intraday_sell_stt_rate: float
    delivery_buy_stamp_rate: float
    intraday_buy_stamp_rate: float
    intraday_brokerage_rate: float
    intraday_brokerage_cap: float
    delivery_brokerage_rate: float = 0.0
    dp_sell_fee_per_scrip: float = 0.0

    def charges(
        self,
        *,
        turnover: float,
        side: Side,
        product: Product,
        executed_orders: int = 1,
        include_dp: bool = False,
    ) -> float:
        if turnover < 0:
            raise ValueError("turnover cannot be negative")
        if executed_orders < 1:
            raise ValueError("executed_orders must be positive")
        if side == Side.HOLD or turnover == 0:
            return 0.0

        if product == Product.DELIVERY:
            brokerage = turnover * self.delivery_brokerage_rate
            stt = turnover * self.delivery_stt_rate
            stamp = turnover * self.delivery_buy_stamp_rate if side == Side.BUY else 0.0
            dp = self.dp_sell_fee_per_scrip if include_dp and side == Side.SELL else 0.0
        else:
            raw_brokerage = turnover * self.intraday_brokerage_rate
            brokerage = min(raw_brokerage, self.intraday_brokerage_cap * executed_orders)
            stt = turnover * self.intraday_sell_stt_rate if side == Side.SELL else 0.0
            stamp = turnover * self.intraday_buy_stamp_rate if side == Side.BUY else 0.0
            dp = 0.0

        exchange = turnover * self.exchange_transaction_rate
        sebi = turnover * self.sebi_rate
        gst = (brokerage + exchange + sebi) * self.gst_rate
        return brokerage + stt + exchange + sebi + gst + stamp + dp


ZERODHA_NSE_CASH_2026 = EquityChargeSchedule(
    name="zerodha_nse_cash_2026",
    effective_from=date(2026, 1, 1),
    exchange_transaction_rate=0.0000307,
    sebi_rate=0.000001,
    gst_rate=0.18,
    delivery_stt_rate=0.001,
    intraday_sell_stt_rate=0.00025,
    delivery_buy_stamp_rate=0.00015,
    intraday_buy_stamp_rate=0.00003,
    intraday_brokerage_rate=0.0003,
    intraday_brokerage_cap=20.0,
    delivery_brokerage_rate=0.0,
    dp_sell_fee_per_scrip=15.34,
)


class CostScheduleRegistry:
    def __init__(self, schedules: list[EquityChargeSchedule]) -> None:
        if not schedules:
            raise ValueError("at least one charge schedule is required")
        self.schedules = sorted(schedules, key=lambda item: item.effective_from)

    def for_date(self, value: date) -> EquityChargeSchedule:
        eligible = [item for item in self.schedules if item.effective_from <= value]
        if not eligible:
            raise ValueError(f"No charge schedule configured for {value.isoformat()}")
        return eligible[-1]
