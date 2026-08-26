from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile


@dataclass(frozen=True)
class OllamaCredentials:
    api_key: str

    def __post_init__(self) -> None:
        if not self.api_key.strip():
            raise ValueError("Ollama API key is required")
        if len(self.api_key) > 4096:
            raise ValueError("Ollama API key is unexpectedly long")


class OllamaCredentialStore:
    """Permission-restricted Ollama API-key storage in the persistent volume."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def save(self, credentials: OllamaCredentials) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=self.path.parent,
            prefix=".ollama-credentials-",
            delete=False,
        ) as handle:
            json.dump(asdict(credentials), handle)
            handle.flush()
            os.fchmod(handle.fileno(), 0o600)
            temp_path = Path(handle.name)
        temp_path.replace(self.path)
        self.path.chmod(0o600)

    def load(self) -> OllamaCredentials | None:
        if not self.path.exists():
            return None
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        return OllamaCredentials(api_key=str(payload["api_key"]))

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)
