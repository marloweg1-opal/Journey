"""Nonblocking local process lock; the OS releases ownership on process exit."""
from contextlib import contextmanager
import os


class ProcessBusyError(RuntimeError):
    pass


@contextmanager
def process_lock(path):
    # Never unlink a lock file: doing so could create two independently locked files.
    with open(path, 'a+b') as handle:
        handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            import errno
            if exc.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                raise ProcessBusyError('A media inventory batch is already running') from exc
            raise
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
