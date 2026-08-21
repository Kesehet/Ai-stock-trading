from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, Field, model_validator


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class Product(StrEnum):
    DELIVERY = "DELIVERY"
    INTRADAY = "INTRADAY"


class TradeIntent(BaseModel):
    """Validated AI/strategy proposal. This is never a raw broker payload."""

    symbol: str = Field(min_length=1, max_length=32, pattern=r"^[A-Z0-9&.-]+$")
    side: Side
    product: Product
    thesis_id: str = Field(min_length=1, max_length=128)
    strategy_id: str = Field(min_length=1, max_length=128)
    target_allocation_pct: Annotated[float, Field(ge=0, le=1)]
    entry_min: Annotated[float, Field(gt=0)] | None = None
    entry_max: Annotated[float, Field(gt=0)] | None = None
    stop_price: Annotated[float, Field(gt=0)] | None = None
    target_price: Annotated[float, Field(gt=0)] | None = None
    confidence: Annotated[float, Field(ge=0, le=1)] = 0.5
    horizon: str = Field(min_length=1, max_length=64)
    evidence_ids: tuple[str, ...] = ()
    decision_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    data_cutoff_at: datetime

    @model_validator(mode="after")
    def validate_geometry(self) -> "TradeIntent":
        if self.side == Side.HOLD and self.target_allocation_pct != 0:
            raise ValueError("HOLD must have target_allocation_pct=0")
        if self.entry_min is not None and self.entry_max is not None and self.entry_min > self.entry_max:
            raise ValueError("entry_min cannot exceed entry_max")
        if self.side == Side.BUY and self.entry_max is not None:
            if self.stop_price is not None and self.stop_price >= self.entry_max:
                raise ValueError("BUY stop_price must be below entry range")
            if self.target_price is not None and self.target_price <= self.entry_max:
                raise ValueError("BUY target_price must be above entry range")
        if self.data_cutoff_at > self.decision_at:
            raise ValueError("data_cutoff_at cannot be after decision_at")
        return self


class Quote(BaseModel):
    symbol: str
    last_price: Annotated[float, Field(gt=0)]
    as_of: datetime


class Position(BaseModel):
    symbol: str
    quantity: int
    average_price: Annotated[float, Field(gt=0)]
    product: Product


class OrderPlan(BaseModel):
    intent_id: str
    symbol: str
    side: Side
    product: Product
    quantity: Annotated[int, Field(gt=0)]
    limit_price: Annotated[float, Field(gt=0)] | None = None
    stop_price: Annotated[float, Field(gt=0)] | None = None
    target_price: Annotated[float, Field(gt=0)] | None = None


class RiskDecision(BaseModel):
    approved: bool
    reason: str
    order_plan: OrderPlan | None = None
