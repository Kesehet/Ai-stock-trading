from __future__ import annotations

from pathlib import Path
from time import time

from app.config import Settings


def main() -> None:
    settings = Settings()
    heartbeat = Path(settings.heartbeat_path)
    if not heartbeat.exists():
        raise SystemExit("heartbeat missing")
    age = time() - heartbeat.stat().st_mtime
    if age > max(30.0, settings.runtime_poll_seconds * 3):
        raise SystemExit(f"heartbeat stale: {age:.1f}s")


if __name__ == "__main__":
    main()
