"""Signals: hooks that run around every task, like Celery's ``task_prerun`` & co.

Connect a receiver in a module listed in ``INIT_MODULES`` (imported once, when the
function starts) so it is registered before the first task runs::

    from celery_cloud.signals import task_failure

    @task_failure.connect
    def report(task_id=None, task=None, exception=None, **kwargs):
        ...

Receivers are called with keyword arguments, so declare ``**kwargs``: new ones may be
added. A receiver that raises is logged and ignored; it never breaks the task.

====================  ===========================================================
Signal                Keyword arguments
====================  ===========================================================
``task_prerun``       ``task_id``, ``task`` (name), ``args``, ``kwargs``
``task_postrun``      the above + ``retval`` and ``state`` (SUCCESS, FAILURE, RETRY,
                      IGNORED, REJECTED)
``task_success``      ``task_id``, ``task``, ``result``
``task_failure``      ``task_id``, ``task``, ``exception``, ``traceback``
``task_retry``        ``task_id``, ``task``, ``reason``, ``eta``
====================  ===========================================================
"""

import logging
from collections.abc import Callable
from typing import Any

_log = logging.getLogger("celery_cloud.signals")


class Signal:
    """A list of receivers that are called with keyword arguments."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._receivers: list[Callable[..., Any]] = []

    def connect(self, receiver: Callable[..., Any]) -> Callable[..., Any]:
        """Register ``receiver`` (usable as a decorator); twice is a no-op."""
        if receiver not in self._receivers:
            self._receivers.append(receiver)
        return receiver

    def disconnect(self, receiver: Callable[..., Any]) -> None:
        if receiver in self._receivers:
            self._receivers.remove(receiver)

    def send(self, **kwargs: Any) -> None:
        """Call every receiver; their errors are logged, never raised."""
        for receiver in list(self._receivers):
            try:
                receiver(**kwargs)
            except Exception:
                _log.exception("Receiver %r of signal %s failed", receiver, self.name)


task_prerun = Signal("task_prerun")
task_postrun = Signal("task_postrun")
task_success = Signal("task_success")
task_failure = Signal("task_failure")
task_retry = Signal("task_retry")
