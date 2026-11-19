"""Local tasks: plain functions packaged with the runner.

Every local task receives two parameters: the list of positional arguments and
the dict of keyword arguments that the client sent.
"""

from celery_cloud.logging import logger


def add(args: list[int], kwargs: dict[str, int]) -> int:
    """Add all the positional arguments (plus the optional ``extra`` keyword)."""
    logger.info("add called with args={} kwargs={}", args, kwargs)
    return sum(args) + kwargs.get("extra", 0)


def subtract(args: list[int], kwargs: dict[str, int]) -> int:
    """Subtract every value from the first one."""
    if len(args) < 2:
        # Any exception becomes a FAILURE state that the client can read
        raise ValueError("subtract needs at least 2 values")
    result = args[0]
    for value in args[1:]:
        result -= value
    return result


def divide(args: list[int], kwargs: dict[str, int]) -> float:
    """Divide the first value by the second one (fails when it is zero)."""
    return args[0] / args[1]


def total(args: list, kwargs: dict) -> int:
    """Chord body: receives ONE argument, the list of results of the header tasks."""
    return sum(args[0])


def report_error(args: list, kwargs: dict) -> str:
    """Error callback (``link_error``): receives the id of the task that failed."""
    logger.warning("task {} failed", args[0])
    return f"handled failure of {args[0]}"
