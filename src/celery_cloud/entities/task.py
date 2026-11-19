from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class Task(BaseModel):
    """Representation of a celery SQS task

    Args:
        BaseModel (_type_): _description_
    """

    task: str = Field(
        ...,
        max_length=150,
        json_schema_extra={
            "description": "Celery task name",
            "example": "task.add",
        },
    )

    # TODO: should be UUID
    id: str = Field(
        ...,
        max_length=150,
        json_schema_extra={
            "description": "Unique task id",
            "example": "4b8f27d1-cd8b-4b79-a1d5-937c5d3579d7",
        },
    )

    args: list[Any] = Field(
        ...,
        json_schema_extra={
            "description": "Positional arguments for the task",
            "example": "1,2",
        },
    )

    kwargs: dict[str, Any] = Field(
        ...,
        json_schema_extra={
            "description": "Named arguments for the task",
            "example": "{'key': 'value'}",
        },
    )

    retries: int | None = Field(
        default=0,
        json_schema_extra={
            "description": "Number of retries",
            "example": "0",
        },
    )

    eta: str | None = Field(
        default=None,
        json_schema_extra={
            "description": (
                "Deferred execution time (ISO8601). The runner holds the task "
                "until then (see eta_seconds)."
            ),
            "example": "2025-03-11T09:56:48+00:00",
        },
    )

    expires: str | None = Field(
        default=None,
        json_schema_extra={
            "description": (
                "Expiration time (ISO8601). A task received after it is not run."
            ),
            "example": "2025-03-11T09:56:48+00:00",
        },
    )

    ignore_result: bool = Field(
        default=False,
        json_schema_extra={
            "description": "When true nothing is stored in the result backend",
        },
    )

    queue: str | None = Field(default=None)
    parent_id: str | None = Field(default=None)
    root_id: str | None = Field(default=None)
    group: str | None = Field(default=None)
    group_index: int | None = Field(default=None)

    # Canvas: signatures (dicts) carried in the ``embed`` part of the message body
    callbacks: list[dict[str, Any]] | None = Field(default=None)
    errbacks: list[dict[str, Any]] | None = Field(default=None)
    chain: list[dict[str, Any]] | None = Field(default=None)
    chord: dict[str, Any] | None = Field(default=None)

    time_limit: float | None = Field(
        default=None,
        json_schema_extra={"description": "Hard time limit in seconds (header)"},
    )

    soft_time_limit: float | None = Field(
        default=None,
        json_schema_extra={"description": "Soft time limit in seconds (header)"},
    )

    def eta_seconds(self, now: datetime | None = None) -> float | None:
        """Seconds until ``eta`` (None when there is none or it is not valid)."""
        if not self.eta:
            return None
        try:
            eta = datetime.fromisoformat(self.eta)
        except ValueError:
            return None
        if eta.tzinfo is None:
            eta = eta.replace(tzinfo=UTC)
        return (eta - (now or datetime.now(UTC))).total_seconds()

    def is_expired(self, now: datetime | None = None) -> bool:
        """True when the task has an ``expires`` time that already passed.

        An unparseable value is treated as "does not expire" rather than
        discarding a task over a malformed header.
        """
        if not self.expires:
            return False
        try:
            expires_at = datetime.fromisoformat(self.expires)
        except ValueError:
            return False
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        return expires_at <= (now or datetime.now(UTC))
