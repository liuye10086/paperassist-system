"""One monotonic numerical deadline shared by an entire business node."""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
import math
import signal
import sys
import threading
import time
from app.domain.regression.common import NumericError

_CURRENT = ContextVar('fixed_statistics_scope', default=None)


class NumericExecutionScope:
    def __init__(self, deadline, receipts=None):
        self.deadline = deadline
        self._receipts = [] if receipts is None else receipts

    def remaining_seconds(self):
        return max(0., self.deadline - time.monotonic())

    def execution_receipts(self):
        return deepcopy(self._receipts)


@contextmanager
def numeric_execution_scope(timeout_seconds=60):
    if type(timeout_seconds) not in (float, int) or not 0 < timeout_seconds <= 60 or not math.isfinite(timeout_seconds):
        raise NumericError('numeric_timeout_invalid', '固定统计节点超时配置无效。')
    parent = _CURRENT.get()
    deadline = time.monotonic() + timeout_seconds
    scope = NumericExecutionScope(min(deadline, parent.deadline) if parent else deadline,
                                  parent._receipts if parent else None)
    token = _CURRENT.set(scope)
    # Production numerical nodes run on the Linux worker child's main thread.
    # A signal deadline also interrupts pool checkout, libpq waits and trusted
    # parent-side preparation; a child-only timeout cannot bound those steps.
    timed = sys.platform == 'linux'
    previous_handler = previous_timer = timer_started = None
    try:
        if timed:
            if threading.current_thread() is not threading.main_thread():
                raise NumericError('numeric_environment_unavailable', '统计节点需要受监督的 Linux Worker 主线程。')
            previous_handler = signal.getsignal(signal.SIGALRM)
            previous_timer = signal.getitimer(signal.ITIMER_REAL)
            timer_started = time.monotonic()
            def timeout(signum, frame):
                raise NumericError('numeric_timeout', '统计节点期限已到。')
            signal.signal(signal.SIGALRM, timeout)
            seconds = scope.remaining_seconds()
            if previous_timer[0] > 0:
                seconds = min(seconds, previous_timer[0])
            signal.setitimer(signal.ITIMER_REAL, max(seconds, 0.000001))
        yield scope
        if scope.remaining_seconds() <= 0:
            raise NumericError('numeric_timeout', '统计节点期限已到。')
    except NumericError as exc:
        # Capture actual measurements before the local numerical scope ends.
        exc.execution_receipt = dict(schema_version=1, status='failed',
            nodes=scope.execution_receipts(), error_code=exc.code)
        raise
    finally:
        if timed and previous_handler is not None:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous_handler)
            if previous_timer[0] > 0:
                remaining = max(0.000001, previous_timer[0] - (time.monotonic() - timer_started))
                signal.setitimer(signal.ITIMER_REAL, remaining, previous_timer[1])
        _CURRENT.reset(token)


def remaining_seconds():
    scope = _CURRENT.get()
    return scope.remaining_seconds() if scope else 30.


def scope_active():
    return _CURRENT.get() is not None


def execution_receipts():
    scope = _CURRENT.get()
    return scope.execution_receipts() if scope else []


def record_execution(receipt):
    scope = _CURRENT.get()
    if scope:
        scope._receipts.append(deepcopy(receipt))
