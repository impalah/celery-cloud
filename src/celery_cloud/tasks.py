"""Celery-like API for local tasks (``task://module/function``).

The original contract keeps working: a plain function ``f(args, kwargs)`` receives the
list of positional arguments and the dict of keyword arguments. Decorating a function
with :func:`task` switches it to the natural calling convention and adds what Celery's
``@app.task`` offers: ``bind``, ``self.request``, ``self.retry()``,
``self.update_state()``, ``autoretry_for``, backoff and time limits::

    from celery_cloud import task

    @task(bind=True, max_retries=3, default_retry_delay=30)
    def fetch(self, url: str) -> str:
        try:
            return download(url)
        except ConnectionError as exc:
            raise self.retry(exc=exc)
"""

import logging
import random
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, NoReturn

from celery_cloud.exceptions import (
    Ignore,
    MaxRetriesExceededError,
    Reject,
    Retry,
)
from celery_cloud.runtime import get_runtime

_MARKER = "__celery_cloud_task__"


@dataclass(frozen=True)
class TaskOptions:
    """Options of a decorated task (same names and defaults as Celery)."""

    name: str | None = None
    bind: bool = False
    max_retries: int | None = 3
    default_retry_delay: float = 180
    autoretry_for: tuple[type[BaseException], ...] = ()
    retry_backoff: bool | float = False
    retry_backoff_max: float = 600
    retry_jitter: bool = True
    soft_time_limit: float | None = None
    time_limit: float | None = None
    # Celery's Task.on_success / on_failure / on_retry, as callables:
    #   on_success(retval, task_id, args, kwargs)
    #   on_failure(exc, task_id, args, kwargs, traceback)
    #   on_retry(exc, task_id, args, kwargs, traceback)
    on_success: Callable[..., Any] | None = None
    on_failure: Callable[..., Any] | None = None
    on_retry: Callable[..., Any] | None = None


@dataclass
class TaskRequest:
    """What the task knows about the message that is being executed."""

    id: str
    task: str
    args: list[Any] = field(default_factory=list)
    kwargs: dict[str, Any] = field(default_factory=dict)
    retries: int = 0
    eta: str | None = None
    expires: str | None = None
    parent_id: str | None = None
    root_id: str | None = None
    group: str | None = None
    group_index: int | None = None
    hostname: str = "celery-cloud"
    delivery_info: dict[str, Any] = field(default_factory=dict)
    callbacks: list[dict[str, Any]] | None = None
    errbacks: list[dict[str, Any]] | None = None
    chain: list[dict[str, Any]] | None = None
    chord: dict[str, Any] | None = None
    time_limit: float | None = None
    soft_time_limit: float | None = None
    is_eager: bool = False


class TaskContext:
    """``self`` of a bound task."""

    def __init__(self, request: TaskRequest, options: TaskOptions) -> None:
        self.request = request
        self.options = options

    @property
    def name(self) -> str:
        return self.request.task

    @property
    def max_retries(self) -> int | None:
        return self.options.max_retries

    def retry(
        self,
        exc: BaseException | None = None,
        countdown: float | None = None,
        eta: datetime | None = None,
        max_retries: int | None = None,
        **_ignored: Any,
    ) -> NoReturn:
        """Ask the runner to run this task again later (use as ``raise self.retry()``).

        Args:
            exc: The exception that caused the retry; it is the failure reported when
                the retries run out.
            countdown: Seconds to wait (default: ``default_retry_delay``).
            eta: Absolute time of the next attempt; wins over ``countdown``.
            max_retries: Overrides the ``max_retries`` of the task.

        Raises:
            Retry: Always, unless the retries are exhausted, in which case ``exc`` is
                raised (or ``MaxRetriesExceededError`` when there is none).
        """
        limit = self.options.max_retries if max_retries is None else max_retries
        if limit is not None and self.request.retries >= limit:
            if exc is not None:
                raise exc
            raise MaxRetriesExceededError(
                f"Can't retry {self.request.task}[{self.request.id}] "
                f"args:{self.request.args} kwargs:{self.request.kwargs}"
            )
        if countdown is None and eta is None:
            countdown = self.options.default_retry_delay
        raise Retry(exc=exc, countdown=countdown, eta=eta)

    def update_state(
        self,
        task_id: str | None = None,
        state: str | None = None,
        meta: Any = None,
        **_ignored: Any,
    ) -> None:
        """Store a custom state (e.g. ``PROGRESS``) that the client reads with
        ``result.state`` and ``result.info``.
        """
        runtime = get_runtime()
        if runtime is None or state is None:
            return
        runtime.update_state(task_id or self.request.id, state, meta)

    def is_revoked(self) -> bool:
        """True when the client revoked this task (cooperative cancellation)."""
        runtime = get_runtime()
        return runtime.is_revoked(self.request.id) if runtime else False


def task[F: Callable[..., Any]](func: F | None = None, /, **options: Any) -> Any:
    """Decorator that turns a function into a Celery-like local task.

    Usable as ``@task`` or ``@task(bind=True, max_retries=5)``. The function stays
    directly callable (handy in unit tests).
    """
    task_options = TaskOptions(**options)

    def decorate[T: Callable[..., Any]](function: T) -> T:
        setattr(function, _MARKER, task_options)
        return function

    return decorate(func) if func is not None else decorate


def get_options(function: Callable[..., Any]) -> TaskOptions | None:
    """The options of a decorated task, None for a plain ``f(args, kwargs)``."""
    options = getattr(function, _MARKER, None)
    return options if isinstance(options, TaskOptions) else None


def backoff_countdown(options: TaskOptions, retries: int) -> float:
    """Seconds to wait before retry number ``retries + 1`` (exponential backoff).

    Same formula as Celery: ``min(retry_backoff_max, factor * 2**retries)``, with
    ``retry_jitter`` picking a random value between 0 and that.
    """
    if options.retry_backoff is False:
        return options.default_retry_delay
    factor = 1.0 if options.retry_backoff is True else float(options.retry_backoff)
    countdown = float(min(options.retry_backoff_max, factor * (2**retries)))
    if options.retry_jitter:
        return float(random.randrange(int(countdown) + 1))  # nosec B311
    return countdown


def call_task_function(function: Callable[..., Any], request: TaskRequest) -> Any:
    """Call a task function with the convention it was written for."""
    options = get_options(function)
    if options is None:
        return function(request.args, request.kwargs)

    context = TaskContext(request, options)
    try:
        if options.bind:
            result = function(context, *request.args, **request.kwargs)
        else:
            result = function(*request.args, **request.kwargs)
    except (Ignore, Reject):
        raise
    except Retry as retry:
        _hook(options.on_retry, retry.exc or retry, request)
        raise
    except options.autoretry_for as error:
        try:
            context.retry(
                exc=error, countdown=backoff_countdown(options, request.retries)
            )
        except Retry as retry:
            _hook(options.on_retry, error, request)
            raise retry from error
        except BaseException as exhausted:
            _hook(options.on_failure, exhausted, request)
            raise
    except Exception as error:
        _hook(options.on_failure, error, request)
        raise
    if options.on_success is not None:
        _hook(options.on_success, result, request)
    return result


def _hook(
    callback: Callable[..., Any] | None, subject: Any, request: TaskRequest
) -> None:
    """Call an ``on_success`` / ``on_failure`` / ``on_retry`` hook; it never raises."""
    if callback is None:
        return
    try:
        if isinstance(subject, BaseException):
            text = "".join(
                traceback.format_exception(
                    type(subject), subject, subject.__traceback__
                )
            )
            callback(subject, request.id, request.args, request.kwargs, text)
        else:
            callback(subject, request.id, request.args, request.kwargs)
    except Exception:
        logging.getLogger("celery_cloud.tasks").exception(
            "Hook %r of task %s failed", callback, request.task
        )
