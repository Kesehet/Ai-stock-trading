from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile


@dataclass(frozen=True)
class RuntimeState:
    session_date: str = ""
    daily_start_equity: float = 0.0
    history_warm_date: str = ""
    last_decisions: dict[str, str] | None = None

    @property
    def decisions(self) -> dict[str, str]:
        return dict(self.last_decisions or {})


class RuntimeStateStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self) -> RuntimeState:
        if not self.path.exists():
            return RuntimeState(last_decisions={})
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        return RuntimeState(
            session_date=str(payload.get("session_date") or ""),
            daily_start_equity=float(payload.get("daily_start_equity") or 0.0),
            history_warm_date=str(payload.get("history_warm_date") or ""),
            last_decisions={
                str(key): str(value)
                for key, value in dict(payload.get("last_decisions") or {}).items()
            },
        )

    def save(self, state: RuntimeState) -> RuntimeState:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "session_date": state.session_date,
            "daily_start_equity": state.daily_start_equity,
            "history_warm_date": state.history_warm_date,
            "last_decisions": state.decisions,
        }
        with NamedTemporaryFile("w", encoding="utf-8", dir=self.path.parent, delete=False) as handle:
            json.dump(payload, handle, sort_keys=True)
            temp_path = Path(handle.name)
        temp_path.replace(self.path)
        return state

    def ensure_daily_baseline(self, today: date, equity: float) -> RuntimeState:
        state = self.load()
        key = today.isoformat()
        if state.session_date == key and state.daily_start_equity > 0:
            return state
        return self.save(
            RuntimeState(
                session_date=key,
                daily_start_equity=equity,
                history_warm_date=state.history_warm_date,
                last_decisions=state.decisions,
            )
        )

    def set_history_warm(self, today: date) -> RuntimeState:
        state = self.load()
        return self.save(
            RuntimeState(
                session_date=state.session_date,
                daily_start_equity=state.daily_start_equity,
                history_warm_date=today.isoformat(),
                last_decisions=state.decisions,
            )
        )

    def record_decision(self, symbol: str, when: datetime) -> RuntimeState:
        state = self.load()
        decisions = state.decisions
        decisions[symbol.upper()] = when.isoformat()
        return self.save(
            RuntimeState(
                session_date=state.session_date,
                daily_start_equity=state.daily_start_equity,
                history_warm_date=state.history_warm_date,
                last_decisions=decisions,
            )
        )
