"""One server owns recovery and background processing for each private workspace."""

import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .operations import OperationBusy


@contextmanager
def server_owner(data: Path) -> Iterator[None]:
    data.mkdir(parents=True, exist_ok=True)
    with (data / ".server-lock").open("a+b") as lock:
        if lock.tell() == 0:
            lock.write(b"\0")
            lock.flush()
        lock.seek(0)
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise OperationBusy(
                "Another server already owns this workspace. Stop it before starting another."
            ) from exc
        try:
            yield
        finally:
            if sys.platform == "win32":
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
