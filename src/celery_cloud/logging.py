import contextvars
import sys
from typing import Any

from loguru import logger

from .settings import settings

# Create a context variable to store the trace_id
trace_id_context: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "trace_id", default=None
)


def add_trace_id(record: Any) -> bool:
    """Add the trace_id to the log record

    Args:
        record: Loguru log record.

    Returns:
        bool: Always True, so the record is not filtered out.
    """
    trace_id = trace_id_context.get()
    record["extra"]["trace_id"] = trace_id if trace_id else "N/A"
    return True


# Configure the logger
logger.remove()

# stderr Logger
logger.add(
    sink=sys.stderr,
    level=settings.LOG_LEVEL,
    format=settings.LOG_FORMAT,
    filter=add_trace_id,
    colorize=None,  # auto: no ANSI escape codes when stderr is not a tty (CloudWatch)
    serialize=False,
    backtrace=True,
    # Do not dump local variables (task arguments) into the logs unless asked
    diagnose=settings.LOG_DIAGNOSE,
    # Do not use multiprocessing for the logs (AWS Lambda)
    enqueue=settings.LOG_ENQUEUE,
)

__all__ = [
    "logger",
    "trace_id_context",
]
