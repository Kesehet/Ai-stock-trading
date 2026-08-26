from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import urlparse


@dataclass(frozen=True)
class OllamaCredentials:
    base_url: str
    model: str
    api_key: str

    def __post_init__(self) -> None:
        url = self.base_url.strip().rstrip("/")
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("Ollama cloud URL must be a valid HTTPS URL")
        if not self.model.strip():
            raise ValueError("Ollama model is required")
        if not self.api_key.strip():
            raise ValueError("Ollama API key is required")
        if len(self.api_key) > 4096:
            raise ValueError("Ollama API key is unexpectedly long")
        object.__setattr__(self, "base_url", url)
        object.__setattr__(self, "model", self.model.strip())


class OllamaCredentialStore:
    """Permission-restricted remote Ollama configuration storage."""

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
        return OllamaCredentials(
            base_url=str(payload["base_url"]),
            model=str(payload["model"]),
            api_key=str(payload["api_key"]),
        )

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)
