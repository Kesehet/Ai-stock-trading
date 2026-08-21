from __future__ import annotations

import csv
from dataclasses import dataclass
from io import StringIO

import httpx

from app.evidence.models import EvidenceKind, SourceTier
from app.evidence.sources import RSSSource, RSSSourceConfig
from app.instruments import Instrument, InstrumentMaster


NSE_EQUITY_SECURITIES_URL = (
    "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
)


@dataclass(frozen=True)
class NSEInstrumentSource:
    url: str = NSE_EQUITY_SECURITIES_URL
    timeout_seconds: float = 30.0

    def fetch(self) -> InstrumentMaster:
        with httpx.Client(timeout=self.timeout_seconds, follow_redirects=True) as client:
            response = client.get(
                self.url,
                headers={"User-Agent": "ai-stock-trading/0.1 research-ingestor"},
            )
            response.raise_for_status()
        return parse_nse_equity_csv(response.text)


def parse_nse_equity_csv(content: str) -> InstrumentMaster:
    rows = csv.DictReader(StringIO(content))
    instruments: list[Instrument] = []
    for row in rows:
        symbol = (row.get("SYMBOL") or row.get("symbol") or "").strip().upper()
        name = (
            row.get("NAME OF COMPANY")
            or row.get("NAME_OF_COMPANY")
            or row.get("name")
            or symbol
        ).strip()
        isin = (
            row.get("ISIN NUMBER")
            or row.get("ISIN_NUMBER")
            or row.get("isin")
            or ""
        ).strip().upper()
        series = (
            row.get(" SERIES")
            or row.get("SERIES")
            or row.get("series")
            or ""
        ).strip().upper()
        if not symbol or not isin:
            continue
        if series and series != "EQ":
            continue
        instruments.append(
            Instrument(
                exchange="NSE",
                symbol=symbol,
                name=name,
                isin=isin,
                instrument_id=f"NSE:{isin}",
            )
        )
    return InstrumentMaster(instruments)


def nse_rss_source(
    *,
    name: str,
    url: str,
    kind: EvidenceKind,
    trust_score: float = 1.0,
) -> RSSSource:
    return RSSSource(
        RSSSourceConfig(
            name=name,
            url=url,
            source_tier=SourceTier.OFFICIAL,
            trust_score=trust_score,
            kind=kind,
        )
    )
