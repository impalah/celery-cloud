import base64
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from celery_cloud import messaging
from celery_cloud.entities import SQSMessage, SQSRecord
from celery_cloud.exceptions import BackendException
from celery_cloud.messaging import MAX_DELAY_SECONDS, QueueRef
from sqs_helpers import build_sqs_record

NOW = datetime(2030, 5, 1, 12, 0, 0, tzinfo=UTC)
ARN = "arn:aws:sqs:eu-west-1:123456789012:my-queue"


def decode(body: str) -> tuple[dict, list]:
    """The envelope and the ``[args, kwargs, embed]`` body of a message."""
    envelope = json.loads(base64.b64decode(body))
    return envelope, json.loads(base64.b64decode(envelope["body"]))


def as_task(body: str):
    """Read a built message with the same code that reads real Celery messages."""
    record = SQSRecord.model_validate(
        {
            **build_sqs_record(),
            "body": body,
        }
    )
    return SQSMessage.from_record(record).get_task()


# -- queues --------------------------------------------------------------------


def test_queue_ref_from_arn_and_url():
    ref = QueueRef.from_arn(ARN)
    assert ref == QueueRef("aws", "eu-west-1", "123456789012", "my-queue")
    assert ref.url() == "https://sqs.eu-west-1.amazonaws.com/123456789012/my-queue"


def test_queue_url_in_china_partition():
    ref = QueueRef.from_arn("arn:aws-cn:sqs:cn-north-1:123456789012:q")
    assert ref.url() == "https://sqs.cn-north-1.amazonaws.com.cn/123456789012/q"


@pytest.mark.parametrize(
    "arn", ["", "not an arn", "arn:aws:s3:::bucket", "arn:aws:sqs:eu-west-1:1:a:b"]
)
def test_queue_ref_rejects_what_is_not_a_queue_arn(arn):
    with pytest.raises(ValueError, match="Not an SQS queue ARN"):
        QueueRef.from_arn(arn)


def test_another_queue_of_the_same_account():
    other = QueueRef.from_arn(ARN).named("other")
    assert other.url() == "https://sqs.eu-west-1.amazonaws.com/123456789012/other"


# -- sending -------------------------------------------------------------------


def test_send_calls_sqs_with_the_url_and_delay():
    client = MagicMock()
    with patch.object(messaging, "_sqs_client", return_value=client) as factory:
        messaging.send(QueueRef.from_arn(ARN), "BODY", 30)
    factory.assert_called_once_with("eu-west-1")
    client.send_message.assert_called_once_with(
        QueueUrl="https://sqs.eu-west-1.amazonaws.com/123456789012/my-queue",
        MessageBody="BODY",
        DelaySeconds=30,
    )


@pytest.mark.parametrize("asked,sent", [(-5, 0), (0, 0), (899, 899), (5000, 900)])
def test_send_keeps_the_delay_inside_the_sqs_limits(asked, sent):
    client = MagicMock()
    with patch.object(messaging, "_sqs_client", return_value=client):
        messaging.send(QueueRef.from_arn(ARN), "BODY", asked)
    assert client.send_message.call_args.kwargs["DelaySeconds"] == sent
    assert MAX_DELAY_SECONDS == 900


def test_send_failure_is_a_backend_exception():
    client = MagicMock()
    client.send_message.side_effect = RuntimeError("queue deleted")
    with patch.object(messaging, "_sqs_client", return_value=client):
        with pytest.raises(BackendException) as raised:
            messaging.send(QueueRef.from_arn(ARN), "BODY")
    assert raised.value.message == "Could not send a message to queue my-queue"
    assert raised.value.detail == "queue deleted"


@pytest.mark.parametrize(
    "seconds,expected", [(0.2, 1), (1.0, 1), (5.01, 6), (899.5, 900), (4000, 900)]
)
def test_delay_message_rounds_up_and_clamps(seconds, expected):
    record = SQSRecord.model_validate(build_sqs_record())
    with patch.object(messaging, "send") as send:
        assert messaging.delay_message(record, seconds) == expected
    queue, body, delay = send.call_args.args
    assert queue == QueueRef.from_arn(ARN)
    assert body == record.body  # the very same message
    assert delay == expected


def test_retry_message_updates_retries_and_eta_only():
    record = SQSRecord.model_validate(build_sqs_record(args=[1, 2], kwargs={"a": 1}))
    eta = NOW + timedelta(seconds=30)

    envelope, body = decode(messaging.retry_message(record, 2, eta))

    assert envelope["headers"]["retries"] == 2
    assert envelope["headers"]["eta"] == eta.isoformat()
    assert envelope["headers"]["id"] == "task-1"  # same task id
    assert body[0] == [1, 2] and body[1] == {"a": 1}
    assert as_task(messaging.retry_message(record, 2, eta)).retries == 2


def test_retry_message_without_eta_clears_it():
    record = SQSRecord.model_validate(build_sqs_record(headers={"eta": "2030-01-01"}))
    envelope, _ = decode(messaging.retry_message(record, 1, None))
    assert envelope["headers"]["eta"] is None


# -- building messages from signatures -----------------------------------------


def signature(**changes):
    sig = {
        "task": "calc.add",
        "args": [10],
        "kwargs": {"k": 1},
        "options": {},
        "subtask_type": None,
        "immutable": False,
    }
    sig.update(changes)
    return sig


def test_build_message_prepends_the_previous_result():
    task_id, body = messaging.build_message(
        signature(), (5,), queue="q", parent_id="p-1", root_id="r-1", now=NOW
    )
    task = as_task(body)
    assert task.id == task_id
    assert task.task == "calc.add"
    assert task.args == [5, 10]
    assert task.kwargs == {"k": 1}
    assert (task.parent_id, task.root_id) == ("p-1", "r-1")
    assert task.queue == "q"
    assert task.retries == 0


def test_build_message_immutable_signatures_ignore_the_previous_result():
    _, body = messaging.build_message(
        signature(immutable=True), (5,), queue="q", now=NOW
    )
    assert as_task(body).args == [10]


def test_build_message_generates_a_task_id_and_uses_it_as_root():
    task_id, body = messaging.build_message(signature(), queue="q", now=NOW)
    assert len(task_id) == 36
    assert as_task(body).root_id == task_id


def test_build_message_uses_the_task_id_of_the_signature():
    sig = signature(options={"task_id": "fixed-id"})
    task_id, _ = messaging.build_message(sig, queue="q", now=NOW)
    assert task_id == "fixed-id"


def test_build_message_carries_the_canvas_in_the_embed():
    callbacks = [signature(task="cb")]
    errbacks = [signature(task="eb")]
    chord = signature(task="body")
    sig = signature(
        options={"link": callbacks, "link_error": errbacks, "chord": chord}
    )
    chain = [signature(task="c1")]
    _, body = messaging.build_message(sig, queue="q", chain=chain, now=NOW)
    task = as_task(body)
    assert task.callbacks == callbacks
    assert task.errbacks == errbacks
    assert task.chord == chord
    assert task.chain == chain


def test_build_message_group_and_limits_options():
    sig = signature(
        options={
            "group_id": "g-1",
            "group_index": 2,
            "time_limit": 60,
            "soft_time_limit": 30,
            "ignore_result": True,
        }
    )
    envelope, body = decode(messaging.build_message(sig, queue="q", now=NOW)[1])
    assert envelope["headers"]["group"] == "g-1"
    assert envelope["headers"]["group_index"] == 2
    assert envelope["headers"]["timelimit"] == [60, 30]
    assert envelope["headers"]["ignore_result"] is True
    task = as_task(messaging.build_message(sig, queue="q", now=NOW)[1])
    assert (task.time_limit, task.soft_time_limit) == (60, 30)
    assert task.group == "g-1" and task.group_index == 2


def test_build_message_countdown_and_expires_become_absolute_times():
    sig = signature(options={"countdown": 90, "expires": 600})
    envelope, _ = decode(messaging.build_message(sig, queue="q", now=NOW)[1])
    assert envelope["headers"]["eta"] == (NOW + timedelta(seconds=90)).isoformat()
    assert envelope["headers"]["expires"] == (NOW + timedelta(seconds=600)).isoformat()


def test_build_message_keeps_an_absolute_eta():
    sig = signature(options={"eta": "2031-01-01T00:00:00+00:00"})
    envelope, _ = decode(messaging.build_message(sig, queue="q", now=NOW)[1])
    assert envelope["headers"]["eta"] == "2031-01-01T00:00:00+00:00"


def test_build_message_properties_follow_the_celery_protocol():
    task_id, body = messaging.build_message(signature(), queue="the-queue", now=NOW)
    envelope, embed_body = decode(body)
    properties = envelope["properties"]
    assert properties["correlation_id"] == task_id
    assert properties["delivery_info"] == {"exchange": "", "routing_key": "the-queue"}
    assert properties["body_encoding"] == "base64"
    assert envelope["content-type"] == "application/json"
    assert envelope["headers"]["lang"] == "py"
    assert embed_body[2] == {
        "callbacks": None,
        "errbacks": None,
        "chain": None,
        "chord": None,
    }


def test_build_message_argsrepr_is_truncated():
    sig = signature(args=["x" * 5000])
    envelope, _ = decode(messaging.build_message(sig, queue="q", now=NOW)[1])
    assert len(envelope["headers"]["argsrepr"]) == 1024


# -- the protocol: what a Celery client (kombu) writes, field by field -----------------


def test_a_built_message_has_exactly_the_shape_of_a_celery_message():
    """Golden test: the header and property names and constant values of a real message.

    Captured from Celery 5.7 / kombu 5.7 (SQS transport): the runner's messages must be
    indistinguishable from the ones a client sends, because a real worker may read them.
    """
    task_id, body = messaging.build_message(
        signature(args=[1], kwargs={"k": 2}, options={"task_id": "T-1"}),
        queue="the-queue",
        parent_id="P-1",
        root_id="R-1",
        now=NOW,
    )
    envelope, embed_body = decode(body)

    assert set(envelope) == {
        "body", "content-encoding", "content-type", "headers", "properties",
    }
    assert envelope["content-encoding"] == "utf-8"
    assert envelope["content-type"] == "application/json"
    assert envelope["headers"] == {
        "lang": "py",
        "task": "calc.add",
        "id": "T-1",
        "shadow": None,
        "eta": None,
        "expires": None,
        "group": None,
        "group_index": None,
        "retries": 0,
        "timelimit": [None, None],
        "root_id": "R-1",
        "parent_id": "P-1",
        "argsrepr": "(1,)",
        "kwargsrepr": "{'k': 2}",
        "origin": "celery-cloud",
        "ignore_result": False,
        "replaced_task_nesting": 0,
        "stamped_headers": None,
        "stamps": {},
    }
    properties = envelope["properties"]
    assert set(properties) == {
        "correlation_id", "reply_to", "delivery_mode", "delivery_info", "priority",
        "body_encoding", "delivery_tag",
    }
    assert properties["correlation_id"] == "T-1"
    assert properties["reply_to"] is None
    assert properties["delivery_mode"] == 2
    assert properties["delivery_info"] == {"exchange": "", "routing_key": "the-queue"}
    assert properties["priority"] == 0
    assert properties["body_encoding"] == "base64"
    assert len(properties["delivery_tag"]) == 36  # a uuid, not "None"
    assert embed_body == [[1], {"k": 2}, {
        "callbacks": None, "errbacks": None, "chain": None, "chord": None,
    }]


def test_the_reply_to_option_is_carried():
    sig = signature(options={"reply_to": "reply-queue"})
    envelope, _ = decode(messaging.build_message(sig, queue="q", now=NOW)[1])
    assert envelope["properties"]["reply_to"] == "reply-queue"


def test_the_eta_is_not_computed_from_a_missing_clock():
    """An ``eta`` option that is a number is relative to *now*, not to a fixed date."""
    sig = signature(options={"eta": 120})
    envelope, _ = decode(messaging.build_message(sig, queue="q", now=NOW)[1])
    assert envelope["headers"]["eta"] == (NOW + timedelta(seconds=120)).isoformat()


def test_without_a_clock_the_current_time_is_used():
    sig = signature(options={"countdown": 60})
    envelope, _ = decode(messaging.build_message(sig, queue="q")[1])
    eta = datetime.fromisoformat(envelope["headers"]["eta"])
    assert abs((eta - datetime.now(UTC)).total_seconds() - 60) < 5


def test_the_chain_of_the_signature_is_used_when_none_is_given():
    chain = [signature(task="from.options")]
    sig = signature(options={"chain": chain})
    _, body = messaging.build_message(sig, queue="q", now=NOW)
    assert as_task(body).chain == chain


def test_an_explicit_empty_chain_replaces_the_one_of_the_signature():
    sig = signature(options={"chain": [signature(task="old")]})
    _, body = messaging.build_message(sig, queue="q", chain=[], now=NOW)
    # build_message stores [] as given; the runner treats it as "no more steps"
    assert decode(body)[1][2]["chain"] == []


def test_kwargsrepr_is_truncated_too():
    sig = signature(kwargs={"big": "y" * 5000})
    envelope, _ = decode(messaging.build_message(sig, queue="q", now=NOW)[1])
    assert len(envelope["headers"]["kwargsrepr"]) == 1024


def test_ignore_result_defaults_to_false_and_follows_the_option():
    default, _ = decode(messaging.build_message(signature(), queue="q", now=NOW)[1])
    assert default["headers"]["ignore_result"] is False
    explicit, _ = decode(
        messaging.build_message(
            signature(options={"ignore_result": True}), queue="q", now=NOW
        )[1]
    )
    assert explicit["headers"]["ignore_result"] is True
