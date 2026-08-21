from __future__ import annotations

import csv
from dataclasses import dataclass
from io import StringIO


@dataclass(frozen=True)
class Instrument:
    exchange: str
    symbol: str
    name: str
    isin: str
    instrument_id: str
    sector: str | None = None


class InstrumentMaster:
    """Canonical exchange instrument registry used before any trade can execute."""

    def __init__(self, instruments: list[Instrument]) -> None:
        self._by_id = {item.instrument_id.upper(): item for item in instruments}
        self._by_symbol = {(item.exchange.upper(), item.symbol.upper()): item for item in instruments}
        self._by_isin = {item.isin.upper(): item for item in instruments if item.isin}
        self._by_name = {self._normalize(item.name): item for item in instruments}

    @staticmethod
    def _normalize(value: str) -> str:
        return " ".join(value.upper().replace("LIMITED", "").replace("LTD", "").split())

    def get(self, instrument_id: str) -> Instrument | None:
        return self._by_id.get(instrument_id.upper())

    def resolve(
        self,
        query: str,
        exchange: str = "NSE",
    ) -> Instrument | None:
        raw = query.strip().upper()
        if not raw:
            return None
        by_id = self._by_id.get(raw)
        if by_id is not None:
            return by_id
        by_symbol = self._by_symbol.get((exchange.upper(), raw))
        if by_symbol is not None:
            return by_symbol
        by_isin = self._by_isin.get(raw)
        if by_isin is not None:
            return by_isin
        return self._by_name.get(self._normalize(query))

    def require(self, query: str, exchange: str = "NSE") -> Instrument:
        instrument = self.resolve(query, exchange)
        if instrument is None:
            raise ValueError(f"Unknown instrument: {query}")
        return instrument

    @classmethod
    def from_csv(cls, content: str) -> InstrumentMaster:
        rows = csv.DictReader(StringIO(content))
        instruments: list[Instrument] = []
        for row in rows:
            exchange = (row.get("exchange") or "NSE").strip().upper()
            symbol = (row.get("symbol") or "").strip().upper()
            isin = (row.get("isin") or "").strip().upper()
            name = (row.get("name") or symbol).strip()
            if not symbol or not isin:
                continue
            instrument_id = (row.get("instrument_id") or f"{exchange}:{isin}").strip()
            sector = (row.get("sector") or "").strip() or None
            instruments.append(
                Instrument(
                    exchange=exchange,
                    symbol=symbol,
                    name=name,
                    isin=isin,
                    instrument_id=instrument_id,
                    sector=sector,
                )
            )
        return cls(instruments)
