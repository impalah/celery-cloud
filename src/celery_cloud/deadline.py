"""Time limits for task execution.

Celery's ``soft_time_limit`` / ``time_limit`` and the Lambda timeout are enforced
with ``SIGALRM`` timers, so a task that runs too long is stopped *by the runner*,
which can then store a ``FAILURE`` result. Without this AWS kills the function at
its timeout, nothing is stored and the task stays in ``STARTED`` forever.

Limits:
  * Signals only work in the main thread of the process (that is where AWS Lambda
    runs the handler). In any other thread the limits are silently not enforced.
  * ``SIGALRM`` is delivered between Python bytecodes and interrupts blocking
    system calls. A C extension that never returns control cannot be interrupted;
    the Lambda timeout remains the last safety net.
"""

import math
import signal
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager

from celery_cloud.exceptions import SoftTimeLimitExceeded, TimeLimitExceeded


def _fmt(seconds: float) -> str:
    return str(int(seconds)) if float(seconds).is_integer() else f"{seconds:g}"


def signals_available() -> bool:
    """True when ``SIGALRM`` timers can be used (main thread, POSIX)."""
    return (
        hasattr(signal, "setitimer")
        and threading.current_thread() is threading.main_thread()
    )


def remaining_seconds(context: object) -> float | None:
    """Seconds left before AWS kills the invocation, or None if unknown."""
    getter = getattr(context, "get_remaining_time_in_millis", None)
    if getter is None:
        return None
    try:
        millis = getter()
    except Exception:
        return None
    # Not a number (e.g. a mock): the remaining time is unknown
    if isinstance(millis, bool) or not isinstance(millis, int | float):
        return None
    return float(millis) / 1000.0


@contextmanager
def time_limits(
    soft: float | None,
    hard: float | None,
    hard_reason: str | None = None,
) -> Iterator[None]:
    """Raise ``SoftTimeLimitExceeded`` / ``TimeLimitExceeded`` in the running code.

    Args:
        soft: Seconds after which ``SoftTimeLimitExceeded`` is raised.
        hard: Seconds after which ``TimeLimitExceeded`` is raised.
        hard_reason: Text for the hard exception (default ``TimeLimitExceeded(N,)``).
    """
    stages: list[tuple[float, Exception]] = []
    if soft is not None and soft > 0:
        soft_error = SoftTimeLimitExceeded(f"SoftTimeLimitExceeded({_fmt(soft)},)")
        stages.append((soft, soft_error))
    if hard is not None and hard > 0:
        default_reason = f"TimeLimitExceeded({_fmt(hard)},)"
        hard_error = TimeLimitExceeded(hard_reason or default_reason)
        stages.append((hard, hard_error))
    if not stages or not signals_available():
        yield
        return

    stages.sort(key=lambda stage: stage[0])
    started = time.monotonic()

    def on_alarm(signum: int, frame: object) -> None:
        _, error = stages.pop(0)
        if stages:
            wait = max(stages[0][0] - (time.monotonic() - started), 0.001)
            signal.setitimer(signal.ITIMER_REAL, wait)
        raise error

    previous = signal.signal(signal.SIGALRM, on_alarm)
    signal.setitimer(signal.ITIMER_REAL, stages[0][0])
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def effective_limits(
    task_soft: float | None,
    task_hard: float | None,
    seconds_left: float | None,
    margin: float,
) -> tuple[float | None, float | None, str | None]:
    """Combine the limits of the task with the time the Lambda has left.

    Returns:
        ``(soft, hard, hard_reason)``. The hard limit is the smaller of the task's
        own and ``seconds_left - margin``, so the failure can be stored before AWS
        stops the function.
    """
    hard = task_hard
    reason: str | None = None
    if seconds_left is not None:
        budget = max(seconds_left - margin, 0.001)
        if hard is None or budget < hard:
            hard = budget
            reason = (
                "The Lambda function is about to reach its timeout "
                f"(stopped after {math.floor(budget)} s)"
            )
    return task_soft, hard, reason
