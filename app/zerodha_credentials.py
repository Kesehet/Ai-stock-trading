from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile


@dataclass(frozen=True)
class ZerodhaCredentials:
    api_key: str
    api_secret: str

    def __post_init__(self) -> None:
        if not self.api_key.strip() or not self.api_secret.strip():
            raise ValueError("Zerodha API key and secret are required")
        if len(self.api_key) > 256 or len(self.api_secret) > 256:
            raise ValueError("Zerodha credentials are unexpectedly long")


class ZerodhaCredentialStore:
    """Permission-restricted credential storage in the persistent data volume."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def save(self, credentials: ZerodhaCredentials) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=self.path.parent,
            prefix=".zerodha-credentials-",
            delete=False,
        ) as handle:
            json.dump(asdict(credentials), handle)
            handle.flush()
            os.fchmod(handle.fileno(), 0o600)
            temp_path = Path(handle.name)
        temp_path.replace(self.path)
        self.path.chmod(0o600)

    def load(self) -> ZerodhaCredentials | None:
        if not self.path.exists():
            return None
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        return ZerodhaCredentials(
            api_key=str(payload["api_key"]),
            api_secret=str(payload["api_secret"]),
        )

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)
