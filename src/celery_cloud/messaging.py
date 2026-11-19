"""Send Celery messages to SQS from the runner.

The runner needs to publish messages in three cases: to hold a task until its ``eta``
(it sends the same message back with a delay), to retry a task (same message with an
updated ``retries``/``eta`` header) and to start the next task of a canvas (a message
built from a signature). Messages follow Celery's protocol 2, the format that the
Celery client (kombu) writes: ``base64(json(envelope))`` with the body, headers and
properties, where the envelope body is ``base64(json([args, kwargs, embed]))``.
"""

import base64
import functools
import json
import math
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, NamedTuple

import boto3
from botocore.config import Config

from celery_cloud.entities import SQSRecord
from celery_cloud.exceptions import BackendException

# SQS limit for DelaySeconds
MAX_DELAY_SECONDS = 900


class QueueRef(NamedTuple):
    """An SQS queue, as found in the ``eventSourceARN`` of a record."""

    partition: str
    region: str
    account: str
    name: str

    @classmethod
    def from_arn(cls, arn: str) -> "QueueRef":
        parts = arn.split(":")
        if len(parts) != 6 or parts[2] != "sqs":
            raise ValueError(f"Not an SQS queue ARN: {arn!r}")
        return cls(parts[1], parts[3], parts[4], parts[5])

    def url(self) -> str:
        suffix = "amazonaws.com.cn" if self.partition == "aws-cn" else "amazonaws.com"
        return f"https://sqs.{self.region}.{suffix}/{self.account}/{self.name}"

    def named(self, name: str) -> "QueueRef":
        """Another queue of the same account and Region."""
        return self._replace(name=name)


@functools.lru_cache(maxsize=8)
def _sqs_client(region: str) -> Any:
    return boto3.client(
        "sqs",
        region_name=region,
        config=Config(retries={"max_attempts": 3, "mode": "standard"}),
    )


def encode_body(envelope: dict[str, Any]) -> str:
    """The SQS message body kombu writes for a Celery message envelope."""
    return base64.b64encode(json.dumps(envelope).encode()).decode()


def send(queue: QueueRef, body: str, delay_seconds: int = 0) -> None:
    """Send a message body to a queue.

    Raises:
        BackendException: When SQS rejects or cannot receive the message.
    """
    delay = max(0, min(int(delay_seconds), MAX_DELAY_SECONDS))
    try:
        _sqs_client(queue.region).send_message(
            QueueUrl=queue.url(), MessageBody=body, DelaySeconds=delay
        )
    except Exception as e:
        raise BackendException(
            message=f"Could not send a message to queue {queue.name}", detail=str(e)
        ) from e


def delay_message(record: SQSRecord, seconds: float) -> int:
    """Send the message of ``record`` back to its queue, delayed. Returns the delay."""
    # round up: the task must never run before its eta
    delay = max(1, min(math.ceil(seconds), MAX_DELAY_SECONDS))
    send(QueueRef.from_arn(record.eventSourceARN), record.body, delay)
    return delay


def retry_message(record: SQSRecord, retries: int, eta: datetime | None) -> str:
    """The body of ``record`` with the ``retries`` and ``eta`` headers updated."""
    envelope = record.get_message()
    headers = envelope["headers"]
    headers["retries"] = retries
    headers["eta"] = eta.isoformat() if eta else None
    return encode_body(envelope)


def _iso(value: Any, now: datetime) -> str | None:
    """``eta``/``expires`` of a signature as an ISO string (seconds are relative)."""
    if value is None:
        return None
    if isinstance(value, int | float):
        return (now + timedelta(seconds=value)).isoformat()
    return str(value)


def build_message(
    signature: dict[str, Any],
    args_prefix: Sequence[Any] = (),
    *,
    queue: str,
    parent_id: str | None = None,
    root_id: str | None = None,
    chain: list[dict[str, Any]] | None = None,
    now: datetime | None = None,
) -> tuple[str, str]:
    """Build the message that runs a Celery signature (as a client would send it).

    Args:
        signature: A signature dict (``task``, ``args``, ``kwargs``, ``options``,
            ``immutable``), the format Celery puts in ``link``, ``chain`` and ``chord``.
        args_prefix: Arguments placed before the signature's own (the result of the
            previous task). Ignored when the signature is immutable.
        queue: Name of the queue the message is for (its routing key).
        parent_id: Id of the task that triggers this one.
        root_id: Id of the first task of the workflow.
        chain: Remaining steps of a chain to carry in the message.
        now: Clock, for tests.

    Returns:
        ``(task_id, sqs_message_body)``.
    """
    now = now or datetime.now(UTC)
    options: dict[str, Any] = signature.get("options") or {}
    task_id = str(options.get("task_id") or uuid.uuid4())
    own_args = list(signature.get("args") or [])
    args = own_args if signature.get("immutable") else [*args_prefix, *own_args]
    kwargs = signature.get("kwargs") or {}

    eta = _iso(options.get("eta"), now)
    if eta is None and options.get("countdown") is not None:
        eta = _iso(options["countdown"], now)
    embed = {
        "callbacks": options.get("link"),
        "errbacks": options.get("link_error"),
        "chain": chain if chain is not None else options.get("chain"),
        "chord": options.get("chord"),
    }
    headers = {
        "lang": "py",
        "task": signature["task"],
        "id": task_id,
        "shadow": None,
        "eta": eta,
        "expires": _iso(options.get("expires"), now),
        "group": options.get("group_id"),
        "group_index": options.get("group_index"),
        "retries": 0,
        "timelimit": [options.get("time_limit"), options.get("soft_time_limit")],
        "root_id": root_id or task_id,
        "parent_id": parent_id,
        "argsrepr": repr(tuple(args))[:1024],
        "kwargsrepr": repr(kwargs)[:1024],
        "origin": "celery-cloud",
        "ignore_result": bool(options.get("ignore_result", False)),
        "replaced_task_nesting": 0,
        "stamped_headers": None,
        "stamps": {},
    }
    properties = {
        "correlation_id": task_id,
        "reply_to": options.get("reply_to"),
        "delivery_mode": 2,
        "delivery_info": {"exchange": "", "routing_key": queue},
        "priority": 0,
        "body_encoding": "base64",
        "delivery_tag": str(uuid.uuid4()),
    }
    body = base64.b64encode(json.dumps([args, kwargs, embed]).encode()).decode()
    envelope = {
        "body": body,
        "content-encoding": "utf-8",
        "content-type": "application/json",
        "headers": headers,
        "properties": properties,
    }
    return task_id, encode_body(envelope)
