"""Exceptions raised *inside* task code by the runner itself.

They are plain ``Exception`` subclasses (not ``RunnerBaseException``) because
user code can catch them, exactly as with Celery's own classes of the same name.
``celery_module`` tells the runner which module to report in a ``FAILURE`` result:
the Celery client rebuilds the exception from ``exc_module`` + ``exc_type``, so
reporting ``celery.exceptions`` makes ``except celery.exceptions.SoftTimeLimitExceeded``
work on the client.
"""

from datetime import datetime


class SoftTimeLimitExceeded(Exception):
    """The soft time limit of the task expired (the task may clean up)."""

    celery_module = "celery.exceptions"


class TimeLimitExceeded(Exception):
    """The hard time limit expired, or the Lambda function is about to time out."""

    celery_module = "celery.exceptions"


class MaxRetriesExceededError(Exception):
    """``retry()`` was called more times than ``max_retries`` allows."""

    celery_module = "celery.exceptions"


class Retry(Exception):
    """Raised by ``retry()``: the runner re-sends the task instead of failing it.

    Args:
        exc: The exception that caused the retry (reported if retries run out).
        countdown: Seconds to wait before the next attempt.
        eta: Absolute time (``datetime``) of the next attempt; wins over ``countdown``.
    """

    celery_module = "celery.exceptions"

    def __init__(
        self,
        exc: BaseException | None = None,
        countdown: float | None = None,
        eta: datetime | None = None,
        message: str | None = None,
    ) -> None:
        self.exc = exc
        self.countdown = countdown
        self.eta = eta
        self.message = message or (f"Retry: {exc!r}" if exc else "Retry")
        super().__init__(self.message)


class Ignore(Exception):
    """Raised by a task to end without storing any result (the state is left as is).

    Typical use: update the state yourself with ``update_state`` and then
    ``raise Ignore()``.
    """

    celery_module = "celery.exceptions"


class Reject(Exception):
    """Raised by a task to reject its message.

    Args:
        reason: Why it was rejected.
        requeue: When True the message goes back to SQS and the task runs again.
            When False the task is stored as ``REJECTED`` and dropped.
    """

    celery_module = "celery.exceptions"

    def __init__(self, reason: str | None = None, requeue: bool = False) -> None:
        self.reason = reason
        self.requeue = requeue
        super().__init__(reason, requeue)
