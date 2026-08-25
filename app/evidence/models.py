from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


class SourceTier(StrEnum):
    OFFICIAL = "OFFICIAL"
    PRIMARY = "PRIMARY"
    WIRE = "WIRE"
    NEWS = "NEWS"
    SOCIAL = "SOCIAL"


class EvidenceKind(StrEnum):
    ANNOUNCEMENT = "ANNOUNCEMENT"
    FINANCIAL_RESULT = "FINANCIAL_RESULT"
    BOARD_MEETING = "BOARD_MEETING"
    CORPORATE_ACTION = "CORPORATE_ACTION"
    INSIDER_TRADING = "INSIDER_TRADING"
    SHAREHOLDING = "SHAREHOLDING"
    CIRCULAR = "CIRCULAR"
    NEWS = "NEWS"
    MACRO = "MACRO"
    TRANSCRIPT = "TRANSCRIPT"


class MarketEventType(StrEnum):
    UNKNOWN = "UNKNOWN"
    FINANCIAL_RESULTS = "FINANCIAL_RESULTS"
    BOARD_MEETING = "BOARD_MEETING"
    CORPORATE_ACTION = "CORPORATE_ACTION"
    MANAGEMENT_CHANGE = "MANAGEMENT_CHANGE"
    LARGE_ORDER = "LARGE_ORDER"
    ACQUISITION = "ACQUISITION"
    REGULATORY_ACTION = "REGULATORY_ACTION"
    DIVIDEND = "DIVIDEND"
    BUYBACK = "BUYBACK"
    FUNDRAISE = "FUNDRAISE"
    INSIDER_TRADING = "INSIDER_TRADING"
    SHAREHOLDING_CHANGE = "SHAREHOLDING_CHANGE"


class EvidenceItem(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    source_name: str = Field(min_length=1, max_length=128)
    source_tier: SourceTier
    kind: EvidenceKind
    source_url: str = Field(min_length=1)
    source_ref: str | None = None
    title: str = Field(min_length=1)
    body: str = ""
    symbol: str | None = None
    published_at: datetime
    event_at: datetime | None = None
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    available_at: datetime
    trust_score: float = Field(ge=0, le=1)
    fingerprint: str

    @model_validator(mode="after")
    def validate_times(self) -> EvidenceItem:
        for value in (self.published_at, self.retrieved_at, self.available_at, self.event_at):
            if value is not None and value.tzinfo is None:
                raise ValueError("evidence timestamps must be timezone-aware")
        if self.available_at < self.published_at:
            raise ValueError("available_at cannot precede published_at")
        return self

    @staticmethod
    def make_fingerprint(
        source_name: str,
        source_ref: str | None,
        source_url: str,
        title: str,
        published_at: datetime,
    ) -> str:
        stable_ref = source_ref or source_url
        raw = f"{source_name}|{stable_ref}|{title.strip()}|{published_at.isoformat()}"
        return sha256(raw.encode("utf-8")).hexdigest()


class MarketEvent(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    event_type: MarketEventType
    symbol: str | None = None
    occurred_at: datetime | None = None
    detected_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    materiality: float = Field(default=0.5, ge=0, le=1)
    sentiment: float = Field(default=0.0, ge=-1, le=1)
    evidence_ids: tuple[str, ...]
    summary: str
