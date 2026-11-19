import base64
import json
import pytest
from unittest.mock import patch

from celery_cloud.entities import Task
from celery_cloud.entities.sqs_entities import (
    DeliveryInfo,
    Properties,
    Headers,
    SQSMessage,
    SQSRecord,
    SQSAttributes,
    SQSEvent,
)
from celery_cloud.exceptions import (
    EventDecodeException,
    MessageDecodeException,
    TaskDecodeException,
)


def create_valid_headers(**overrides):
    data = {
        "lang": "py",
        "task": "my.task",
        "id": "abc123",
        "shadow": None,
        "eta": None,
        "expires": None,
        "group": None,
        "group_index": None,
        "retries": 0,
        "timelimit": [None, None],
        "root_id": "abc123",
        "parent_id": None,
        "argsrepr": "[]",
        "kwargsrepr": "{}",
        "origin": "unittest",
        "ignore_result": False,
        "replaced_task_nesting": 0,
        "stamped_headers": None,
        "stamps": {},
    }
    return Headers(**{**data, **overrides})


def create_valid_properties():
    return Properties(
        correlation_id="corr-id",
        reply_to="reply-queue",
        delivery_mode=2,
        delivery_info=DeliveryInfo(exchange="default", routing_key="task_queue"),
        priority=0,
        body_encoding="base64",
        delivery_tag="tag-1",
    )


def test_decode_body():
    original = {"hello": "world"}
    body = base64.b64encode(json.dumps(original).encode()).decode()
    msg = SQSMessage(
        body=body,
        content_encoding="utf-8",
        content_type="application/json",
        headers=create_valid_headers(),
        properties=create_valid_properties(),
    )
    assert msg.decode_body() == original


def make_message(body_obj, headers=None, **overrides):
    data = {
        "body": base64.b64encode(json.dumps(body_obj).encode()).decode(),
        "content_encoding": "utf-8",
        "content_type": "application/json",
        "headers": headers or create_valid_headers(),
        "properties": create_valid_properties(),
    }
    return SQSMessage(**{**data, **overrides})


def test_get_task_success():
    msg = make_message(
        [["arg1"], {"x": 1}, {}],
        headers=create_valid_headers(retries=2, eta="2025-01-01T00:00:00+00:00"),
    )
    task = msg.get_task()
    assert isinstance(task, Task)
    assert task.task == "my.task"
    assert task.args == ["arg1"]
    assert task.kwargs == {"x": 1}
    assert task.retries == 2
    assert task.eta == "2025-01-01T00:00:00+00:00"


def test_get_task_ignores_truncated_argsrepr():
    """Regression: args were rebuilt from the truncated argsrepr header."""
    big = "x" * 5000
    msg = make_message(
        [[big], {}, {}],
        headers=create_valid_headers(argsrepr="('" + big[:1000] + "...", kwargsrepr=""),
    )
    assert msg.get_task().args == [big]


def test_get_task_supports_non_literal_values_serialized_as_json():
    msg = make_message(
        [[], {"when": "2025-01-01T00:00:00"}, {}],
        headers=create_valid_headers(argsrepr="(datetime.datetime(2025, 1, 1),)"),
    )
    assert msg.get_task().kwargs == {"when": "2025-01-01T00:00:00"}


def test_get_task_null_args_become_empty():
    assert make_message([None, None, {}]).get_task().args == []


@pytest.mark.parametrize("body", [{}, [], [1], "text", 5])
def test_get_task_invalid_body_shape(body):
    with pytest.raises(TaskDecodeException):
        make_message(body).get_task()


def test_get_task_invalid_body_encoding():
    msg = make_message([[], {}, {}], body="@@not base64@@")
    with pytest.raises(TaskDecodeException):
        msg.get_task()


def test_get_task_invalid_args_type():
    with pytest.raises(TaskDecodeException):
        make_message([{"a": 1}, [], {}]).get_task()


def test_get_task_unsupported_content_type():
    with pytest.raises(TaskDecodeException) as exc:
        make_message([[], {}, {}], content_type="application/x-python-serialize").get_task()
    assert "Unsupported content type" in str(exc.value)


def test_headers_optional_fields_not_needed_by_the_runner():
    headers = Headers(lang="py", task="my.task", id="abc")
    assert headers.retries == 0
    assert headers.stamps == {}
    assert headers.ignore_result is False


def test_from_record_roundtrip(sqs_record):
    record = SQSRecord(**sqs_record(task_name="a.b", task_id="id9", args=[1]))
    task = SQSMessage.from_record(record).get_task()
    assert (task.task, task.id, task.args) == ("a.b", "id9", [1])


@pytest.mark.parametrize(
    "envelope",
    [{}, {"body": "x"}, {"body": 1, "content-encoding": "u", "content-type": "c",
                         "headers": {}, "properties": {}}],
)
def test_from_record_invalid_envelope(sqs_record, envelope):
    record = SQSRecord(**sqs_record())
    record.body = base64.b64encode(json.dumps(envelope).encode()).decode()
    with pytest.raises(MessageDecodeException):
        SQSMessage.from_record(record)


@pytest.mark.parametrize(
    "body", ["###", base64.b64encode(b"not json").decode(),
             base64.b64encode(b"[1, 2]").decode()]
)
def test_record_get_message_invalid(sqs_record, body):
    record = SQSRecord(**sqs_record())
    record.body = body
    with pytest.raises(MessageDecodeException):
        record.get_message()


def test_sqs_record_get_message():
    content = {"foo": "bar"}
    body = base64.b64encode(json.dumps(content).encode()).decode()
    record = SQSRecord(
        messageId="msg-1",
        receiptHandle="abc",
        body=body,
        attributes=SQSAttributes(
            ApproximateReceiveCount="1",
            SentTimestamp="1234567890",
            ApproximateFirstReceiveTimestamp="1234567891",
        ),
        eventSource="aws:sqs",
        eventSourceARN="arn:aws:sqs:eu-west-1:123456789012:my-queue",
    )
    assert record.get_message() == content


def test_sqs_event_from_lambda_success():
    raw_event = {
        "Records": [
            {
                "messageId": "msg-1",
                "receiptHandle": "abc",
                "body": base64.b64encode(json.dumps({"test": "ok"}).encode()).decode(),
                "attributes": {
                    "ApproximateReceiveCount": "1",
                    "SentTimestamp": "1234567890",
                    "ApproximateFirstReceiveTimestamp": "1234567891",
                },
                "eventSource": "aws:sqs",
                "eventSourceARN": "arn:aws:sqs:::my-queue",
            }
        ]
    }
    result = SQSEvent.from_lambda(raw_event)
    assert isinstance(result, SQSEvent)
    assert result.Records[0].messageId == "msg-1"


def test_sqs_event_from_lambda_invalid_structure():
    with pytest.raises(EventDecodeException) as exc:
        SQSEvent.from_lambda({"no_records": []})
    assert "Invalid SQS event format" in str(exc.value)


def test_get_task_validation_error_has_its_own_message():
    """Regression: ValidationError (a ValueError) was swallowed by the generic branch."""
    with pytest.raises(TaskDecodeException) as exc:
        make_message([{"a": 1}, [], {}]).get_task()
    assert exc.value.message == "ValidationError getting task"


def test_get_task_bad_base64_has_decode_message():
    with pytest.raises(TaskDecodeException) as exc:
        make_message([[], {}, {}], body="@@not base64@@").get_task()
    assert exc.value.message == "Error decoding task body"


def test_get_task_unexpected_error_is_wrapped():
    msg = make_message([[], {}, {}])
    with patch.object(SQSMessage, "decode_body", side_effect=RuntimeError("boom")):
        with pytest.raises(TaskDecodeException) as exc:
            msg.get_task()
    assert exc.value.message == "Exception getting task"
    assert "boom" in exc.value.detail


def test_decode_body_without_base64_encoding():
    properties = create_valid_properties()
    properties.body_encoding = "utf-8"
    msg = SQSMessage(
        body=json.dumps([["a"], {"k": 1}, {}]),
        content_encoding="utf-8",
        content_type="application/json",
        headers=create_valid_headers(),
        properties=properties,
    )
    assert msg.decode_body() == [["a"], {"k": 1}, {}]
    assert msg.get_task().args == ["a"]


def test_sqs_event_from_lambda_unexpected_error():
    with patch.object(SQSEvent, "model_validate", side_effect=RuntimeError("boom")):
        with pytest.raises(EventDecodeException) as exc:
            SQSEvent.from_lambda({"Records": []})
    assert exc.value.message == "Error decoding event"
    assert exc.value.detail == "boom"


# ---- exact error contract: message and detail are returned to clients ------


def test_from_record_missing_field_contract(sqs_record):
    record = SQSRecord(**sqs_record())
    record.body = base64.b64encode(json.dumps({}).encode()).decode()
    with pytest.raises(MessageDecodeException) as exc:
        SQSMessage.from_record(record)
    assert exc.value.message == "Missing field in message"
    assert exc.value.detail == "'body'"


def test_from_record_invalid_format_contract(sqs_record):
    record = SQSRecord(**sqs_record())
    envelope = {"body": 1, "content-encoding": "u", "content-type": "c",
                "headers": {}, "properties": {}}
    record.body = base64.b64encode(json.dumps(envelope).encode()).decode()
    with pytest.raises(MessageDecodeException) as exc:
        SQSMessage.from_record(record)
    assert exc.value.message == "Invalid message format"
    assert "body" in exc.value.detail


def test_get_message_error_contracts(sqs_record):
    record = SQSRecord(**sqs_record())

    record.body = "###"
    with pytest.raises(MessageDecodeException) as exc:
        record.get_message()
    assert exc.value.message == "Error decoding message body"
    assert isinstance(exc.value.detail, str) and exc.value.detail not in ("", "None")

    record.body = base64.b64encode(b"[1, 2]").decode()
    with pytest.raises(MessageDecodeException) as exc:
        record.get_message()
    assert exc.value.message == "Error decoding message body"
    assert exc.value.detail == "the message is not a JSON object"


def test_get_task_error_contracts():
    with pytest.raises(TaskDecodeException) as exc:
        make_message([[], {}, {}], content_type="application/x-python-serialize").get_task()
    assert exc.value.message == "Unsupported content type"
    assert exc.value.detail == "application/x-python-serialize"

    with pytest.raises(TaskDecodeException) as exc:
        make_message("text").get_task()
    assert exc.value.message == "Invalid task body"
    assert exc.value.detail == "expected a list [args, kwargs, embed]"

    with pytest.raises(TaskDecodeException) as exc:
        make_message([{"a": 1}, [], {}]).get_task()
    assert exc.value.message == "ValidationError getting task"
    assert "args" in exc.value.detail

    with pytest.raises(TaskDecodeException) as exc:
        make_message([[], {}, {}], body="@@not base64@@").get_task()
    assert exc.value.message == "Error decoding task body"
    assert isinstance(exc.value.detail, str) and exc.value.detail not in ("", "None")


def test_get_task_body_with_exactly_args_and_kwargs_is_valid():
    """A body without the 'embed' element is still a valid [args, kwargs]."""
    task = make_message([["a"], {"k": 1}]).get_task()
    assert (task.args, task.kwargs) == (["a"], {"k": 1})


def test_get_task_body_that_is_not_a_list_is_invalid_even_if_long():
    with pytest.raises(TaskDecodeException) as exc:
        make_message({"a": 1, "b": 2, "c": 3}).get_task()
    assert exc.value.message == "Invalid task body"


def test_from_lambda_invalid_event_detail_is_machine_readable():
    with pytest.raises(EventDecodeException) as exc:
        SQSEvent.from_lambda({"no_records": []})
    assert exc.value.message == "Invalid SQS event format"
    errors = json.loads(exc.value.detail)
    assert errors[0]["loc"] == ["Records"]
