from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile

from app.config import AppMode


@dataclass(frozen=True)
class RuntimeModeState:
    mode: AppMode


class RuntimeModeStore:
    def __init__(self, path: str | Path, default_mode: AppMode = AppMode.PAPER) -> None:
        self.path = Path(path)
        self.default_mode = default_mode

    def load(self) -> RuntimeModeState:
        if not self.path.exists():
            return RuntimeModeState(self.default_mode)
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        return RuntimeModeState(AppMode(str(payload.get("mode", self.default_mode.value))))

    def save(self, mode: AppMode) -> RuntimeModeState:
        if mode not in {AppMode.PAPER, AppMode.LIVE}:
            raise ValueError("runtime mode must be paper or live")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=self.path.parent,
            delete=False,
        ) as handle:
            json.dump({"mode": mode.value}, handle)
            temp_path = Path(handle.name)
        temp_path.replace(self.path)
        return RuntimeModeState(mode)
