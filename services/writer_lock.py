"""Nonblocking OS lock for one local writer, across threads and processes.

Lock files stay in place: unlinking them could let two processes lock different
files with the same name. The OS releases the lock when a process exits.
"""
from contextlib import contextmanager
from functools import wraps
from hashlib import sha256
import os
import threading

from services.config import ROOT, check_writable
from services.errors import BusyError

_guard = threading.Lock()
_held = set()
_local = threading.local()


@contextmanager
def writer_lock(repository):
    identity = getattr(repository, "sheet_id", "default")
    key = sha256(str(identity).encode()).hexdigest()
    nested = getattr(_local, "keys", set())
    if key in nested:
        yield
        return
    with _guard:
        if key in _held:
            raise BusyError("Another operation is updating this Sheet. Wait for it to finish, then refresh and try again.")
        _held.add(key)
    handle = None
    acquired = False
    try:
        folder = ROOT / "var" / "locks"
        folder.mkdir(parents=True, exist_ok=True)
        handle = (folder / f"{key}.lock").open("a+b")
        if handle.seek(0, os.SEEK_END) == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise BusyError("Another process is updating this Sheet. Wait for it to finish, then refresh and try again.") from None
        acquired = True
        _local.keys = nested | {key}
        yield
    finally:
        _local.keys = nested
        if handle:
            if acquired:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle, fcntl.LOCK_UN)
            handle.close()
        with _guard:
            _held.discard(key)


def serialized_write(function):
    @wraps(function)
    def wrapped(repository, *args, **kwargs):
        check_writable()
        with writer_lock(repository):
            return function(repository, *args, **kwargs)
    return wrapped
