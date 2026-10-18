"""Persist local numerical failure without retrying an external generation."""
import logging
from app.adapters.task_execution_store import LeaseLost

logger = logging.getLogger(__name__)


def fail_numeric_task(repository, lease, error):
    try:
        return repository.fail(lease, error.code,
            execution_receipt=getattr(error, 'execution_receipt', None))
    except LeaseLost:
        return None
    except Exception as exc:
        # Only a persistence interruption leaves recovery to the lease owner.
        logger.warning('numeric failure persistence unavailable type=%s', type(exc).__name__)
        return None
