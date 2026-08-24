from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class MacroSnapshot:
    available_at: datetime
    repo_rate: float | None = None
    cpi_yoy: float | None = None
    gdp_yoy: float | None = None
    usd_inr: float | None = None
    crude_usd: float | None = None
    india_vix: float | None = None
    nifty_return_20d: float | None = None

    def as_text(self) -> str:
        values = {
            "repo_rate": self.repo_rate,
            "cpi_yoy": self.cpi_yoy,
            "gdp_yoy": self.gdp_yoy,
            "usd_inr": self.usd_inr,
            "crude_usd": self.crude_usd,
            "india_vix": self.india_vix,
            "nifty_return_20d": self.nifty_return_20d,
        }
        lines = [f"available_at={self.available_at.isoformat()}"]
        lines.extend(
            f"{key}={value:.4f}" if value is not None else f"{key}=NA"
            for key, value in values.items()
        )
        return "\n".join(lines)


class MacroStore:
    def __init__(self, snapshots: list[MacroSnapshot] | None = None) -> None:
        self._snapshots: list[MacroSnapshot] = []
        for snapshot in snapshots or []:
            self.add(snapshot)

    def add(self, snapshot: MacroSnapshot) -> None:
        if snapshot.available_at.tzinfo is None:
            raise ValueError("macro available_at must be timezone-aware")
        self._snapshots.append(snapshot)
        self._snapshots.sort(key=lambda item: item.available_at)

    def latest_as_of(self, cutoff: datetime) -> MacroSnapshot | None:
        visible = [item for item in self._snapshots if item.available_at <= cutoff]
        return visible[-1] if visible else None
