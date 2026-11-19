"""Client-side helpers (optional): the parts of Celery that need the runner's help.

A Celery client cannot revoke a task of this runner by itself: ``app.control.revoke``
broadcasts a message to workers, and there are no workers to receive it. The helpers
here do it through the result backend instead, which the runner already reads::

    from celery_cloud.client import install

    install(app)               # once, after configuring the Celery app
    result.revoke()            # now works: a task that has not started never starts

How it works: ``revoke`` writes a ``REVOKED`` result for the task with a ``revoked``
flag. A task that has not started yet is skipped by the runner. A task that is already
running is only *flagged*: it keeps running unless its code checks
``self.is_revoked()`` (cooperative cancellation), because a running Python function
cannot be stopped safely from outside.

Only ``boto3`` is needed (no runner settings are read).
"""

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import boto3
from botocore.exceptions import ClientError

from celery_cloud import serialization

# Result of ``revoke``: the task had not started (it will never run) / it already
# existed (running or finished), so it was only flagged
REVOKED = "revoked"
FLAGGED = "flagged"


def _key(task_id: str) -> str:
    # The string form of the bytes key, exactly as Celery's DynamoDB backend builds it
    return str(f"celery-task-meta-{task_id}".encode())


def revoke(
    task_id: str,
    *,
    table: str,
    region: str,
    ttl_seconds: int = 86400,
    serializer: str = "json",
    client: Any = None,
) -> str:
    """Revoke a task.

    Args:
        task_id: The Celery task id.
        table: The DynamoDB result table.
        region: The Region of the table.
        ttl_seconds: How long the ``REVOKED`` marker is kept (0 = forever; it only
            expires if TTL is enabled on the table for the ``ttl`` attribute).
        serializer: The ``result_serializer`` of the client (json, msgpack or yaml).
        client: A DynamoDB client (for tests); created from ``region`` by default.

    Returns:
        ``"revoked"`` when the task had not started (it will never run), or
        ``"flagged"`` when it had already started or finished (the flag is only seen by
        a task that checks ``self.is_revoked()``).
    """
    dynamodb = client or boto3.client("dynamodb", region_name=region)
    now = datetime.now(UTC)
    meta: dict[str, Any] = {
        "status": "REVOKED",
        "result": {
            "exc_type": "TaskRevokedError",
            "exc_message": ["revoked"],
            "exc_module": "celery.exceptions",
        },
        "traceback": None,
        "children": [],
        "date_done": now.isoformat(),
        "task_id": task_id,
    }
    item: dict[str, Any] = {
        "id": {"S": _key(task_id)},
        "result": {"B": serialization.dumps(meta, serializer)},
        "timestamp": {"N": str(now.timestamp())},
        "revoked": {"BOOL": True},
    }
    if ttl_seconds > 0:
        item["ttl"] = {"N": str(int(now.timestamp()) + ttl_seconds)}

    try:
        dynamodb.put_item(
            TableName=table,
            Item=item,
            ConditionExpression="attribute_not_exists(id)",
        )
        return REVOKED
    except ClientError as error:
        if error.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise

    dynamodb.update_item(
        TableName=table,
        Key={"id": {"S": _key(task_id)}},
        UpdateExpression="SET revoked = :yes",
        ExpressionAttributeValues={":yes": {"BOOL": True}},
    )
    return FLAGGED


def backend_location(result_backend: str) -> tuple[str, str]:
    """``(region, table)`` of a ``dynamodb://@region/table`` result backend URL."""
    parsed = urlparse(result_backend)
    if parsed.scheme != "dynamodb" or not parsed.hostname or not parsed.path.strip("/"):
        raise ValueError(
            "Expected a result backend like dynamodb://@region/table, "
            f"got {result_backend!r}"
        )
    return parsed.hostname, parsed.path.strip("/")


def install(app: Any, *, ttl_seconds: int = 86400) -> None:
    """Make ``app.control.revoke`` / ``AsyncResult.revoke`` work with this runner.

    Reads the Region and table from the app's ``result_backend``. ``terminate`` and
    ``signal`` are accepted and ignored: a running task is flagged, not killed.
    """
    region, table = backend_location(str(app.conf.result_backend))
    serializer = str(getattr(app.conf, "result_serializer", None) or "json")

    def revoke_tasks(
        task_id: str | Iterable[str], terminate: bool = False, **_ignored: Any
    ) -> None:
        ids = [task_id] if isinstance(task_id, str) else list(task_id)
        for one in ids:
            revoke(
                one,
                table=table,
                region=region,
                ttl_seconds=ttl_seconds,
                serializer=serializer,
            )

    app.control.revoke = revoke_tasks
