from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from time import sleep

import httpx

from app.market_data import Candle, HistoricalDataStore
from app.nse_bhavcopy import NSEBhavcopySource, parse_udiff_zip


@dataclass(frozen=True)
class HistoryLoadResult:
    requested_days: int
    loaded_days: int
    missing_days: int
    candles: int


class NSEHistoryLoader:
    """Download/cache NSE daily UDiFF bhavcopies and build a local historical store."""

    def __init__(
        self,
        cache_dir: str | Path,
        source: NSEBhavcopySource | None = None,
        request_delay_seconds: float = 0.25,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.source = source or NSEBhavcopySource()
        self.request_delay_seconds = request_delay_seconds

    def _path(self, trading_date: date) -> Path:
        return self.cache_dir / f"nse_cm_{trading_date.strftime('%Y%m%d')}.zip"

    def _download(self, trading_date: date) -> bytes | None:
        with httpx.Client(timeout=self.source.timeout_seconds, follow_redirects=True) as client:
            response = client.get(
                self.source.url_for(trading_date),
                headers={
                    "User-Agent": "Mozilla/5.0 ai-stock-trading/0.1",
                    "Accept": "application/zip,application/octet-stream,*/*",
                    "Accept-Language": "en-IN,en;q=0.9",
                },
            )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.content

    def load_range(
        self,
        start: date,
        end: date,
        store: HistoricalDataStore | None = None,
    ) -> tuple[HistoricalDataStore, HistoryLoadResult]:
        if end < start:
            raise ValueError("end cannot precede start")
        target = store or HistoricalDataStore()
        requested_days = loaded_days = missing_days = candle_count = 0
        current = start
        while current <= end:
            if current.weekday() < 5:
                requested_days += 1
                path = self._path(current)
                payload: bytes | None
                if path.exists():
                    payload = path.read_bytes()
                else:
                    payload = self._download(current)
                    if payload is not None:
                        path.write_bytes(payload)
                    if self.request_delay_seconds > 0:
                        sleep(self.request_delay_seconds)
                if payload is None:
                    missing_days += 1
                else:
                    candles = parse_udiff_zip(payload, current)
                    for candle in candles:
                        target.add(candle)
                    loaded_days += 1
                    candle_count += len(candles)
            current += timedelta(days=1)
        return target, HistoryLoadResult(
            requested_days=requested_days,
            loaded_days=loaded_days,
            missing_days=missing_days,
            candles=candle_count,
        )
