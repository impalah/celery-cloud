"""End to end tests: SQS event -> lambda_handler -> simulated DynamoDB (moto).

Only AWS is simulated. The backend code (PynamoDB, serialization, conditional
writes) runs for real, which is what the unit tests with mocks cannot prove.
"""

import json
import sys
import types
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from moto import mock_aws

from celery_cloud.models.task_model import MAX_RESULT_BYTES, TaskModel
from celery_cloud.runners import aws_lambda
from celery_cloud.runners.aws_lambda import lambda_handler

from sqs_helpers import build_sqs_record

REGION = "eu-west-1"


@pytest.fixture
def local_tasks():
    """A real local task module registered in TASKS."""
    module = types.ModuleType("it_tasks")
    module.add = lambda args, kwargs: sum(args)  # type: ignore[attr-defined]
    module.boom = lambda args, kwargs: 1 / 0  # type: ignore[attr-defined]
    module.big = lambda args, kwargs: "x" * (MAX_RESULT_BYTES + 1)  # type: ignore[attr-defined]
    module.now = lambda args, kwargs: datetime(2025, 1, 1, tzinfo=UTC)  # type: ignore[attr-defined]
    sys.modules["it_tasks"] = module
    tasks = {
        "t.add": "task://it_tasks/add",
        "t.boom": "task://it_tasks/boom",
        "t.big": "task://it_tasks/big",
        "t.now": "task://it_tasks/now",
    }
    with patch.object(aws_lambda.settings, "TASKS", tasks):
        yield
    del sys.modules["it_tasks"]


def run(*records):
    return lambda_handler({"Records": list(records)}, None)


def with_headers(record, **headers):
    """Rebuild a record changing Celery headers (eta, expires, ignore_result)."""
    import base64

    envelope = json.loads(base64.b64decode(record["body"]))
    envelope["headers"].update(headers)
    record["body"] = base64.b64encode(json.dumps(envelope).encode()).decode()
    return record


def test_success_is_readable_by_get_task(local_tasks):
    result = run(build_sqs_record("t.add", "id-ok", args=[1, 2, 3]))

    assert result["processed_messages"] == 1
    stored = TaskModel.get_task("id-ok")
    assert stored["task_id"] == "b'celery-task-meta-id-ok'"
    assert stored["result"]["status"] == "SUCCESS"
    assert stored["result"]["result"] == 6
    assert stored["result"]["task_id"] == "id-ok"


def test_failure_is_stored_in_celery_format(local_tasks):
    result = run(build_sqs_record("t.boom", "id-fail"))

    assert result["failed_messages"] == 1
    assert result["batchItemFailures"] == []
    meta = TaskModel.get_task("id-fail")["result"]
    assert meta["status"] == "FAILURE"
    # the ORIGINAL exception is reported, so the client can `except ZeroDivisionError`
    assert meta["result"] == {
        "exc_type": "ZeroDivisionError",
        "exc_message": ["division by zero"],
        "exc_module": "builtins",
    }
    assert "ZeroDivisionError" in meta["traceback"]


def test_unsupported_task_is_failure(local_tasks):
    run(build_sqs_record("unknown.task", "id-unknown"))

    meta = TaskModel.get_task("id-unknown")["result"]
    assert meta["status"] == "FAILURE"
    assert "not supported" in meta["result"]["exc_message"][0]


def test_whole_batch_is_processed_even_if_one_task_fails(local_tasks):
    result = run(
        build_sqs_record("t.boom", "b1", message_id="m1"),
        build_sqs_record("t.add", "b2", args=[5], message_id="m2"),
    )

    assert (result["processed_messages"], result["failed_messages"]) == (1, 1)
    assert TaskModel.get_task("b1")["result"]["status"] == "FAILURE"
    assert TaskModel.get_task("b2")["result"]["result"] == 5


def test_duplicate_delivery_is_not_executed_twice(local_tasks):
    first = run(build_sqs_record("t.add", "dup", args=[1], message_id="m1"))
    assert first["processed_messages"] == 1

    with patch.object(aws_lambda, "call_task") as call:
        second = run(build_sqs_record("t.add", "dup", args=[1], message_id="m1-bis"))

    call.assert_not_called()
    assert second["processed_messages"] == 0
    assert second["skipped_messages"] == 1
    assert second["skipped_tasks"][0] == {
        "message_id": "m1-bis",
        "task_id": "dup",
        "reason": "duplicate message: the task already exists",
    }
    assert second["batchItemFailures"] == []  # a duplicate is not redelivered
    # the original result is untouched
    assert TaskModel.get_task("dup")["result"]["result"] == 1


def test_result_too_large_is_a_clear_failure_without_redelivery(local_tasks):
    result = run(build_sqs_record("t.big", "id-big"))

    assert result["failed_messages"] == 1
    assert result["batchItemFailures"] == []  # retrying cannot help
    meta = TaskModel.get_task("id-big")["result"]
    assert meta["status"] == "FAILURE"
    assert meta["result"]["exc_type"] == "ResultTooLargeException"
    assert "too large" in meta["result"]["exc_message"][0]


def test_non_json_result_is_stored_as_text(local_tasks):
    run(build_sqs_record("t.now", "id-now"))

    assert TaskModel.get_task("id-now")["result"]["result"] == "2025-01-01 00:00:00+00:00"


def test_ignore_result_writes_nothing(local_tasks):
    ok = run(with_headers(build_sqs_record("t.add", "ign-ok", args=[1]), ignore_result=True))
    bad = run(with_headers(build_sqs_record("t.boom", "ign-bad"), ignore_result=True))

    assert ok["processed_messages"] == 1
    assert bad["failed_messages"] == 1
    assert TaskModel.get_task("ign-ok") is None
    assert TaskModel.get_task("ign-bad") is None


def test_expired_task_is_revoked_and_not_executed(local_tasks):
    past = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()

    with patch.object(aws_lambda, "call_task") as call:
        result = run(with_headers(build_sqs_record("t.add", "exp", args=[1]), expires=past))

    call.assert_not_called()
    assert result["skipped_messages"] == 1
    assert "expired" in result["skipped_tasks"][0]["reason"]
    meta = TaskModel.get_task("exp")["result"]
    assert meta["status"] == "REVOKED"
    assert meta["result"]["exc_type"] == "TaskRevokedError"


def test_future_expiration_runs_normally(local_tasks):
    future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()

    result = run(with_headers(build_sqs_record("t.add", "fut", args=[2]), expires=future))

    assert result["processed_messages"] == 1
    assert TaskModel.get_task("fut")["result"]["result"] == 2


def test_backend_outage_requests_redelivery(local_tasks):
    from celery_cloud.exceptions import BackendException

    with patch.object(
        TaskModel, "insert_task", side_effect=BackendException("Error inserting task x")
    ):
        result = run(build_sqs_record("t.add", "down", args=[1], message_id="m-down"))

    assert result["batchItemFailures"] == [{"itemIdentifier": "m-down"}]


def test_update_task_stores_meta_traceback_and_timestamp():
    from datetime import UTC, datetime, timedelta

    inserted = TaskModel.insert_task("meta-1")
    first = TaskModel.get_task("meta-1")["timestamp"]
    assert isinstance(first, float)

    TaskModel.update_task("meta-1", "FAILURE", result={"exc_type": "X"}, traceback="tb text")
    stored = TaskModel.get_task("meta-1")

    meta = stored["result"]
    assert meta["status"] == "FAILURE"
    assert meta["traceback"] == "tb text"
    assert meta["children"] == []
    assert meta["task_id"] == "meta-1"
    done = datetime.fromisoformat(meta["date_done"])
    assert abs(datetime.now(UTC) - done) < timedelta(minutes=1)
    assert isinstance(stored["timestamp"], float)
    assert stored["timestamp"] >= first
    assert inserted.id == "b'celery-task-meta-meta-1'"


def test_update_task_without_traceback_stores_null():
    TaskModel.insert_task("meta-2")
    TaskModel.update_task("meta-2", "SUCCESS", result=1, traceback="")

    assert TaskModel.get_task("meta-2")["result"]["traceback"] is None


def test_handler_responses_contain_only_non_empty_lists(local_tasks):
    ok = run(build_sqs_record("t.add", "r1", args=[1]))
    assert ok["processed_tasks"] == [{"task_id": "r1", "status": "SUCCESS", "result": 1}]
    assert ok["failed_tasks"] is None
    assert ok["skipped_tasks"] is None

    bad = run(build_sqs_record("t.boom", "r2"))
    assert bad["processed_tasks"] is None
    assert bad["skipped_tasks"] is None
    assert bad["failed_tasks"][0]["task_id"] == "r2"
    assert bad["failed_tasks"][0]["message_id"] == "msg-1"


def test_every_record_of_a_successful_batch_is_processed(local_tasks):
    result = run(
        build_sqs_record("t.add", "s1", args=[1], message_id="m1"),
        build_sqs_record("t.add", "s2", args=[2], message_id="m2"),
        build_sqs_record("t.add", "s3", args=[3], message_id="m3"),
    )
    assert [t["task_id"] for t in result["processed_tasks"]] == ["s1", "s2", "s3"]


def test_handler_sets_a_trace_id_while_processing(local_tasks):
    from celery_cloud.logging import trace_id_context

    seen = []
    with patch.object(
        aws_lambda, "call_task", side_effect=lambda task, *_: seen.append(trace_id_context.get())
    ):
        run(build_sqs_record("t.add", "trace-1"))

    assert len(seen) == 1 and isinstance(seen[0], str) and len(seen[0]) > 10


def test_a_skipped_record_does_not_stop_the_rest_of_the_batch(local_tasks):
    run(build_sqs_record("t.add", "first", args=[1], message_id="m0"))

    result = run(
        build_sqs_record("t.add", "first", args=[1], message_id="m1"),  # duplicate
        build_sqs_record("t.add", "second", args=[2], message_id="m2"),
    )

    assert result["skipped_messages"] == 1
    assert [t["task_id"] for t in result["processed_tasks"]] == ["second"]
    assert TaskModel.get_task("second")["result"]["result"] == 2


def test_an_expired_record_does_not_stop_the_rest_of_the_batch(local_tasks):
    past = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()

    result = run(
        with_headers(build_sqs_record("t.add", "old", args=[1], message_id="m1"), expires=past),
        build_sqs_record("t.add", "new", args=[2], message_id="m2"),
    )

    assert result["skipped_messages"] == 1
    assert [t["task_id"] for t in result["processed_tasks"]] == ["new"]


def _raw_item(task_id: str) -> dict:
    """The item exactly as stored in DynamoDB (what Celery's backend reads)."""
    import boto3

    key = f"b'celery-task-meta-{task_id}'"
    return boto3.client("dynamodb", region_name=REGION).get_item(
        TableName=TaskModel.Meta.table_name, Key={"id": {"S": key}}
    )["Item"]


def test_results_carry_a_ttl_attribute_compatible_with_celery(local_tasks):
    """Same attribute name, type (N) and unit (epoch seconds) as Celery's backend."""
    import time

    before = int(time.time())
    run(build_sqs_record("t.add", "ttl-1", args=[1]))
    after = int(time.time())

    item = _raw_item("ttl-1")
    assert set(item["ttl"]) == {"N"}
    expires = int(item["ttl"]["N"])
    assert before + 86400 <= expires <= after + 86400
    assert set(item) == {"id", "result", "timestamp", "ttl"}


def test_ttl_is_refreshed_when_the_task_finishes(local_tasks):
    TaskModel.insert_task("ttl-2")
    started = int(_raw_item("ttl-2")["ttl"]["N"])

    from celery_cloud.models import task_model

    with patch.object(task_model.settings, "RESULT_TTL_SECONDS", 172800):
        TaskModel.update_task("ttl-2", "SUCCESS", result=1)

    finished = int(_raw_item("ttl-2")["ttl"]["N"])
    assert finished >= started + 86400  # 48 h from now, not the 24 h of the insert


def test_no_ttl_attribute_when_expiration_is_disabled(local_tasks):
    from celery_cloud.models import task_model

    with patch.object(task_model.settings, "RESULT_TTL_SECONDS", 0):
        run(build_sqs_record("t.add", "ttl-3", args=[1]))

    assert set(_raw_item("ttl-3")) == {"id", "result", "timestamp"}


def test_failures_and_skips_also_get_a_ttl(local_tasks):
    run(build_sqs_record("t.boom", "ttl-4"))
    assert "ttl" in _raw_item("ttl-4")  # a failed task must not live forever either
