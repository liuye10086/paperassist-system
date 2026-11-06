"""Revoke a leased local bio child and descendants without touching reused PIDs."""
import os
import signal
from pathlib import Path
from app.adapters.task_execution_store import LeaseLost


def process_birth(pid):
    return Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()[19]


def require_not_revoked(cancel_event):
    if cancel_event is not None and cancel_event.is_set():raise LeaseLost()


def terminate_revoked_child(pid,birth,cancel_event):
    if cancel_event is None or not cancel_event.is_set():return False
    try:
        if process_birth(pid)!=birth:return False
        os.killpg(pid,signal.SIGKILL)
        return True
    except (OSError,ValueError,IndexError):return False
