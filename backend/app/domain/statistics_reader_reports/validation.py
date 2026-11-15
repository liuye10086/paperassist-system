"""Bound each complete worker source check, never rendering or failure writes."""
from contextlib import contextmanager
from contextvars import ContextVar

from app.core.exceptions import StorageError
from app.domain.regression.common import NumericError

_WORKER=ContextVar('statistics_legacy_report_verification',default=False)


@contextmanager
def worker_verification():
    token=_WORKER.set(True)
    try:yield
    finally:_WORKER.reset(token)


def _numeric_cause(error):
    seen=set()
    while error is not None and id(error) not in seen:
        if isinstance(error,NumericError):return error
        seen.add(id(error))
        error=error.__cause__ or error.__context__


def numeric_failure(error):
    """Retain the true numeric cause even if an outer DB rollback wraps it."""
    numeric=_numeric_cause(error)
    if numeric is None:return None
    failure=StorageError(numeric.code,numeric.message,422)
    failure.execution_receipt=getattr(numeric,'execution_receipt',None)
    return failure


def validate_sources(check):
    # Read-side source/retry checks retain their existing receipt validation;
    # only the real worker performs bounded independent numerical verification.
    if not _WORKER.get():return check()
    from app.domain.fixed_statistics_runtime import numeric_execution_scope
    from app.domain.statistics_execution.verification import verification_scope
    try:
        with numeric_execution_scope(timeout_seconds=60) as scope, verification_scope():
            try:return check()
            except Exception as error:
                numeric=_numeric_cause(error)
                if isinstance(error,NumericError):raise
                # A DB wrapper may replace a signal/timeout during rollback.
                # Normalize only here; keep global storage semantics unchanged.
                if numeric is not None:raise NumericError(numeric.code,numeric.message) from error
                if scope.remaining_seconds()<=0:raise NumericError('numeric_timeout','统计来源核验期限已到。') from error
                raise
    except NumericError as error:
        # StorageError survives enclosing storage connection context managers;
        # the numeric ContextVar/timer have already been restored at this point.
        raise numeric_failure(error) from error
