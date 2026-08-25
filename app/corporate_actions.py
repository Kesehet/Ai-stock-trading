from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from app.market_data import Candle


class CorporateActionType(StrEnum):
    SPLIT = "SPLIT"
    BONUS = "BONUS"


@dataclass(frozen=True)
class CorporateAction:
    symbol: str
    action_type: CorporateActionType
    effective_at: datetime
    price_factor: float

    def __post_init__(self) -> None:
        if self.effective_at.tzinfo is None:
            raise ValueError("corporate action timestamp must be timezone-aware")
        if self.price_factor <= 0:
            raise ValueError("price_factor must be positive")

    @classmethod
    def split(
        cls,
        symbol: str,
        effective_at: datetime,
        old_face_value: float,
        new_face_value: float,
    ) -> CorporateAction:
        if old_face_value <= 0 or new_face_value <= 0:
            raise ValueError("face values must be positive")
        return cls(
            symbol=symbol.upper(),
            action_type=CorporateActionType.SPLIT,
            effective_at=effective_at,
            price_factor=new_face_value / old_face_value,
        )

    @classmethod
    def bonus(
        cls,
        symbol: str,
        effective_at: datetime,
        bonus_shares: int,
        existing_shares: int,
    ) -> CorporateAction:
        if bonus_shares <= 0 or existing_shares <= 0:
            raise ValueError("bonus ratio must be positive")
        factor = existing_shares / (existing_shares + bonus_shares)
        return cls(
            symbol=symbol.upper(),
            action_type=CorporateActionType.BONUS,
            effective_at=effective_at,
            price_factor=factor,
        )


def adjust_candles(
    candles: list[Candle],
    actions: list[CorporateAction],
) -> list[Candle]:
    applicable = sorted(actions, key=lambda action: action.effective_at)
    adjusted: list[Candle] = []
    for candle in candles:
        factor = 1.0
        for action in applicable:
            if action.symbol != candle.symbol.upper():
                continue
            if candle.timestamp < action.effective_at:
                factor *= action.price_factor
        adjusted.append(
            Candle(
                symbol=candle.symbol,
                timestamp=candle.timestamp,
                open=candle.open * factor,
                high=candle.high * factor,
                low=candle.low * factor,
                close=candle.close * factor,
                volume=candle.volume / factor,
            )
        )
    return adjusted
