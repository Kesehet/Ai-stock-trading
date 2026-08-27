from pathlib import Path
from threading import Event, Thread
from time import sleep

from app.runtime import _heartbeat_worker


def test_heartbeat_worker_updates_while_main_work_is_busy(tmp_path) -> None:
    path = Path(tmp_path) / "heartbeat"
    stop = Event()
    worker = Thread(
        target=_heartbeat_worker,
        args=(path, stop, 0.02),
        daemon=True,
    )
    worker.start()
    sleep(0.05)
    first = path.stat().st_mtime_ns
    sleep(0.06)
    second = path.stat().st_mtime_ns
    stop.set()
    worker.join(timeout=1)

    assert second > first
    assert not worker.is_alive()
