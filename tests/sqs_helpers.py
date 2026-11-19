"""Builders of realistic SQS/Celery events shared by the tests."""

import base64
import json
from typing import Any


def build_sqs_record(
    task_name: str = "my.task",
    task_id: str = "task-1",
    args: list[Any] | None = None,
    kwargs: dict[str, Any] | None = None,
    message_id: str = "msg-1",
    argsrepr: str = "()",
    timelimit: list[float | None] | None = None,
    headers: dict[str, Any] | None = None,
    embed: dict[str, Any] | None = None,
    queue_arn: str = "arn:aws:sqs:eu-west-1:123456789012:my-queue",
) -> dict[str, Any]:
    """Build a realistic SQS record carrying a Celery protocol 2 message."""
    body = [
        args or [],
        kwargs or {},
        {"callbacks": None, "errbacks": None, **(embed or {})},
    ]
    envelope = {
        "body": base64.b64encode(json.dumps(body).encode()).decode(),
        "content-encoding": "utf-8",
        "content-type": "application/json",
        "headers": {
            "lang": "py",
            "task": task_name,
            "id": task_id,
            "shadow": None,
            "eta": None,
            "expires": None,
            "group": None,
            "group_index": None,
            "retries": 0,
            "timelimit": timelimit or [None, None],
            "root_id": task_id,
            "parent_id": None,
            "argsrepr": argsrepr,
            "kwargsrepr": "{}",
            "origin": "gen@host",
            "ignore_result": False,
            "replaced_task_nesting": 0,
            "stamped_headers": None,
            "stamps": {},
            **(headers or {}),
        },
        "properties": {
            "correlation_id": task_id,
            "reply_to": "reply-id",
            "delivery_mode": 2,
            "delivery_info": {"exchange": "", "routing_key": "queue"},
            "priority": 0,
            "body_encoding": "base64",
            "delivery_tag": "tag",
        },
    }
    return {
        "messageId": message_id,
        "receiptHandle": "handle",
        "body": base64.b64encode(json.dumps(envelope).encode()).decode(),
        "attributes": {
            "ApproximateReceiveCount": "1",
            "SentTimestamp": "1234567890",
            "ApproximateFirstReceiveTimestamp": "1234567891",
        },
        "eventSource": "aws:sqs",
        "eventSourceARN": queue_arn,
    }


def record_from_sqs_message(message: dict[str, Any]) -> dict[str, Any]:
    """The Lambda record for a message received from SQS (e.g. one the runner sent)."""
    return {
        "messageId": message["MessageId"],
        "receiptHandle": message["ReceiptHandle"],
        "body": message["Body"],
        "attributes": {
            "ApproximateReceiveCount": "1",
            "SentTimestamp": "1234567890",
            "ApproximateFirstReceiveTimestamp": "1234567891",
        },
        "eventSource": "aws:sqs",
        "eventSourceARN": "arn:aws:sqs:eu-west-1:123456789012:my-queue",
    }
