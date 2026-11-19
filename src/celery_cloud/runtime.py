"""What task code can reach while the runner executes it.

The runner publishes a ``Runtime`` for the duration of a task, and ``TaskContext``
(``self`` of a bound task) talks to it. Keeping this in a context variable lets task
code stay independent from the backend and from AWS.
"""

from contextvars import ContextVar, Token
from typing import Protocol


class Runtime(Protocol):
    """Services the runner offers to the running task."""

    def update_state(self, task_id: str, state: str, meta: object) -> None:
        """Store a custom state (for example ``PROGRESS``) in the backend."""

    def is_revoked(self, task_id: str) -> bool:
        """True when the client asked to revoke the task."""


_current: ContextVar[Runtime | None] = ContextVar("celery_cloud_runtime", default=None)


def set_runtime(runtime: Runtime | None) -> Token[Runtime | None]:
    """Make ``runtime`` the current one; keep the token to restore the previous."""
    return _current.set(runtime)


def reset_runtime(token: Token[Runtime | None]) -> None:
    _current.reset(token)


def get_runtime() -> Runtime | None:
    """The runtime of the task being executed (None outside the runner)."""
    return _current.get()
