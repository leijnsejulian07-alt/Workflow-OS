"""Cross-platform advisory file lock for bounded OFFLINE paper acceptance runs.

Do not delete the lock file: a stable inode/Windows file is necessary to avoid
races between two unrelated processes. Kernel-held locks are released when a
process exits or crashes, so abandoned PIDs do not cause permanent downtime.
This module never grants external side-effect authority.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Iterator


def _lock(file: BinaryIO) -> None:
    file.seek(0)
    if os.name == "nt":
        import msvcrt
        msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(file: BinaryIO) -> None:
    file.seek(0)
    if os.name == "nt":
        import msvcrt
        msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(file.fileno(), fcntl.LOCK_UN)


@contextmanager
def exclusive_paper_run_lock(parent: str | Path) -> Iterator[Path]:
    """Refuse overlapping runs in an output folder; unlock automatically on exit.

    The file remains in place after the run. Do not manually remove it while a
    process might be using it. A crashed process loses the kernel lock.
    """
    supplied = Path(parent).expanduser().absolute()
    root = supplied.resolve()  # canonical file identity prevents alias lock bypass
    root.mkdir(parents=True, exist_ok=True)
    path = root / ".workflow-os-paper.lock"
    fd = os.open(str(path), os.O_CREAT | os.O_RDWR, 0o600)
    stream = os.fdopen(fd, "r+b")
    locked = False
    try:
        if path.stat().st_size == 0:
            stream.write(b"0")
            stream.flush()
        try:
            _lock(stream)
        except (OSError, BlockingIOError) as exc:
            raise RuntimeError("another offline paper run is active; overlap denied") from exc
        locked = True
        yield supplied  # preserve caller's absolute Windows 8.3 path alias
    finally:
        if locked:
            _unlock(stream)
        stream.close()
