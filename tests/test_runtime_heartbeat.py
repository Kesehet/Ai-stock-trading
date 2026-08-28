from pathlib import Path
from threading import Event, Thread
from time import monotonic, sleep

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

    deadline = monotonic() + 1.0
    while not path.exists() and monotonic() < deadline:
        sleep(0.01)
    assert path.exists()
    first = path.stat().st_mtime_ns

    second = first
    deadline = monotonic() + 1.0
    while second <= first and monotonic() < deadline:
        sleep(0.03)
        second = path.stat().st_mtime_ns

    stop.set()
    worker.join(timeout=1)

    assert second > first
    assert not worker.is_alive()
