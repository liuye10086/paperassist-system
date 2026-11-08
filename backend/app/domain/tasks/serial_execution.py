"""A host-shared execution slot, independent of short database transactions."""
from contextlib import contextmanager
import errno
import os
from pathlib import Path
import time


def execution_lock_path(directory=None):
    configured = os.environ.get('PAPERASSIST_EXECUTION_LOCK_FILE')
    if configured:
        return Path(configured).expanduser().resolve()
    if directory is None:
        from app.core.config import get_data_dir
        directory = get_data_dir()
    return Path(directory).resolve() / '.worker-execution.lock'


@contextmanager
def file_lock(path, *, blocking=True):
    """Keep the same inode: closing the descriptor releases even after a crash.

    Linux containers share this path through a host volume. Windows uses a
    one-byte OS lock so local tests and tools observe the same exclusion.
    Nothing in API reads, cancellation or heartbeats acquires this lock.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    acquired = False
    with path.open('a+b') as handle:
        if os.name == 'nt':
            import msvcrt
            # Byte-range locks need a stable byte, including on an empty new file.
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b'\0')
                handle.flush()
            while True:
                handle.seek(0)
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    acquired = True
                    break
                except OSError as exc:
                    if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                        raise
                    if not blocking:
                        break
                    time.sleep(.1)
        else:
            import fcntl
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
                acquired = True
            except BlockingIOError:
                pass
        try:
            yield acquired
        finally:
            if acquired:
                if os.name == 'nt':
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
