"""Keep provider/transport details out of operational application logs."""
from importlib import import_module
import logging


_DETAIL_LOGGERS = ('openai', 'httpx2', 'httpx', 'httpcore')


def configure_safe_logging():
    """Apply a WARNING floor to vendor loggers without changing application logs.

    Finish SDK import first: its OPENAI_LOG environment handling can otherwise
    undo our policy on a later import. Existing children may have explicit DEBUG
    levels; configure them too, since ancestor levels/filters do not gate records
    propagated by a child. Future children inherit the namespace's safe floor.
    Repeated entry-point/client initialization adds no filters or handlers.
    """
    import_module('openai')
    for name in _DETAIL_LOGGERS:
        logger = logging.getLogger(name)
        logger.setLevel(max(logging.WARNING, logger.getEffectiveLevel()))
    for name, logger in logging.Logger.manager.loggerDict.copy().items():
        if isinstance(logger, logging.Logger) and any(
                name.startswith(namespace + '.') for namespace in _DETAIL_LOGGERS):
            logger.setLevel(max(logging.WARNING, logger.getEffectiveLevel()))
