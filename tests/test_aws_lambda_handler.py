from unittest.mock import patch

import pytest

from celery_cloud.exceptions import BackendException, EventDecodeException
from celery_cloud.runners import aws_lambda
from celery_cloud.runners.aws_lambda import lambda_handler
from celery_cloud.logging import trace_id_context


@pytest.fixture
def backend():
    """Replace the DynamoDB backend by recording mocks."""
    with (
        patch.object(aws_lambda.TaskModel, "insert_task") as insert,
        patch.object(aws_lambda.TaskModel, "update_task") as update,
    ):
        yield insert, update


@pytest.fixture
def tasks():
    with patch.object(
        aws_lambda.settings,
        "TASKS",
        {"my.task": "task://mod/fn", "other.task": "task://mod/other"},
    ):
        yield


def test_success(backend, tasks, sqs_record, sqs_event):
    insert, update = backend
    with patch.object(aws_lambda, "call_task", return_value=42) as call:
        result = lambda_handler(sqs_event(sqs_record(args=[1, 2])), None)

    assert result["status"] == "completed"
    assert result["processed_messages"] == 1
    assert result["failed_messages"] == 0
    assert result["processed_tasks"][0]["result"] == 42
    assert result["batchItemFailures"] == []
    assert call.call_args.args[0].args == [1, 2]
    insert.assert_called_once_with(task_uuid="task-1")
    update.assert_called_once_with("task-1", status="SUCCESS", result=42)


def test_unsupported_task_is_marked_as_failure(backend, tasks, sqs_record, sqs_event):
    _, update = backend

    result = lambda_handler(sqs_event(sqs_record(task_name="unknown.task")), None)

    assert result["failed_messages"] == 1
    assert "not supported" in result["failed_tasks"][0]["error"]
    assert result["failed_tasks"][0]["task_id"] == "task-1"
    assert update.call_args.kwargs["status"] == "FAILURE"
    # a poison message must not be redelivered forever
    assert result["batchItemFailures"] == []


def test_failing_task_does_not_lose_the_rest_of_the_batch(
    backend, tasks, sqs_record, sqs_event
):
    """Regression: a failing task used to make the handler return None."""
    _, update = backend

    def fake_call_task(task, *_):
        if task.id == "t1":
            raise aws_lambda.TaskExecutionException("boom", "detail")
        return "ok"

    event = sqs_event(
        sqs_record(task_id="t1", message_id="m1"),
        sqs_record(task_id="t2", message_id="m2"),
        sqs_record(task_id="t3", message_id="m3"),
    )
    with patch.object(aws_lambda, "call_task", side_effect=fake_call_task):
        result = lambda_handler(event, None)

    assert result is not None
    assert result["processed_messages"] == 2
    assert result["failed_messages"] == 1
    assert [t["task_id"] for t in result["processed_tasks"]] == ["t2", "t3"]
    assert result["failed_tasks"][0]["task_id"] == "t1"

    # The failed task is stored as FAILURE (Celery state), not left as STARTED
    failure = [c for c in update.call_args_list if c.kwargs["status"] == "FAILURE"]
    assert len(failure) == 1
    payload = failure[0].kwargs["result"]
    assert payload["exc_type"] == "TaskExecutionException"
    assert "boom" in payload["exc_message"][0]
    assert "TaskExecutionException" in failure[0].kwargs["traceback"]
    # an application failure is not retried by SQS
    assert result["batchItemFailures"] == []


def test_backend_failure_requests_redelivery(tasks, sqs_record, sqs_event):
    event = sqs_event(
        sqs_record(task_id="t1", message_id="m1"),
        sqs_record(task_id="t2", message_id="m2"),
    )

    def insert(task_uuid):
        if task_uuid == "t1":
            raise BackendException("Error inserting task t1", "dynamo down")

    with (
        patch.object(aws_lambda.TaskModel, "insert_task", side_effect=insert),
        patch.object(aws_lambda.TaskModel, "update_task"),
        patch.object(aws_lambda, "call_task", return_value=1),
    ):
        result = lambda_handler(event, None)

    assert result["batchItemFailures"] == [{"itemIdentifier": "m1"}]
    assert result["processed_messages"] == 1
    assert result["failed_messages"] == 1


def test_undecodable_message_is_reported(backend, tasks, sqs_record, sqs_event):
    insert, update = backend
    record = sqs_record()
    record["body"] = "not base64 json!!"

    result = lambda_handler(sqs_event(record), None)

    assert result["failed_messages"] == 1
    assert "Error decoding message body" in result["failed_tasks"][0]["error"]
    assert result["failed_tasks"][0]["task_id"] is None
    insert.assert_not_called()
    update.assert_not_called()


def test_failure_while_storing_failure_is_swallowed(tasks, sqs_record, sqs_event):
    with (
        patch.object(aws_lambda.TaskModel, "insert_task"),
        patch.object(
            aws_lambda.TaskModel, "update_task", side_effect=BackendException("x")
        ),
        patch.object(aws_lambda, "call_task", side_effect=RuntimeError("boom")),
    ):
        result = lambda_handler(sqs_event(sqs_record()), None)

    assert result["failed_messages"] == 1
    assert "boom" in result["failed_tasks"][0]["error"]


def test_trace_id_is_cleared(backend, tasks, sqs_record, sqs_event):
    with patch.object(aws_lambda, "call_task", side_effect=RuntimeError("boom")):
        lambda_handler(sqs_event(sqs_record()), None)
    assert trace_id_context.get() is None


def test_event_decode_error():
    with patch.object(
        aws_lambda.SQSEvent,
        "from_lambda",
        side_effect=EventDecodeException("Bad format", "Extra details"),
    ):
        result = lambda_handler({"bad": "structure"}, None)

    assert result["status"] == "error"
    assert result["message"] == "Bad format"
    assert result["details"] == "Extra details"
    assert trace_id_context.get() is None


def test_generic_exception():
    with patch.object(
        aws_lambda.SQSEvent, "from_lambda", side_effect=Exception("Unexpected crash")
    ):
        result = lambda_handler({"Records": [{}]}, None)

    assert result["status"] == "error"
    assert "General error" in result["message"]
    assert "Unexpected crash" in result["details"]


# ---- exact contracts --------------------------------------------------------


def test_failure_payload_is_celery_format():
    payload = aws_lambda._failure_payload(ValueError("bad"))
    assert payload == {
        "exc_type": "ValueError",
        "exc_message": ["bad"],
        "exc_module": "builtins",
    }
    custom = aws_lambda._failure_payload(aws_lambda.TaskExecutionException("m", "d"))
    assert custom["exc_module"] == "celery_cloud.exceptions.runner_exceptions"


def test_revoked_payload_is_celery_format(sqs_record):
    task = aws_lambda.Task(
        id="t", task="a.b", args=[], kwargs={}, expires="2025-01-01T00:00:00+00:00"
    )
    assert aws_lambda._revoked_payload(task) == {
        "exc_type": "TaskRevokedError",
        "exc_message": ["expired at 2025-01-01T00:00:00+00:00"],
        "exc_module": "celery.exceptions",
    }


def test_success_response_contract(backend, tasks, sqs_record, sqs_event):
    with patch.object(aws_lambda, "call_task", return_value=7):
        result = lambda_handler(sqs_event(sqs_record(task_id="ok-1")), None)

    assert result["processed_tasks"] == [
        {"task_id": "ok-1", "status": "SUCCESS", "result": 7}
    ]
    assert result["failed_tasks"] is None
    assert result["skipped_tasks"] is None
    assert result["skipped_messages"] == 0


def test_unexpected_exception_is_stored_as_failure(backend, tasks, sqs_record, sqs_event):
    _, update = backend
    with patch.object(aws_lambda, "call_task", side_effect=RuntimeError("boom")):
        result = lambda_handler(sqs_event(sqs_record(task_id="u1", message_id="mu")), None)

    failed = result["failed_tasks"][0]
    assert failed == {"task_id": "u1", "message_id": "mu", "error": "Unexpected error: boom"}
    stored = update.call_args.kwargs
    assert stored["status"] == "FAILURE"
    assert stored["result"] == {
        "exc_type": "RuntimeError",
        "exc_message": ["boom"],
        "exc_module": "builtins",
    }
    assert "RuntimeError: boom" in stored["traceback"]
    assert stored["traceback"].startswith("Traceback")


def test_application_error_response_contract(backend, tasks, sqs_record, sqs_event):
    with patch.object(
        aws_lambda, "call_task", side_effect=aws_lambda.TaskExecutionException("m", "d")
    ):
        result = lambda_handler(sqs_event(sqs_record(task_id="a1", message_id="ma")), None)

    assert result["failed_tasks"] == [
        {"task_id": "a1", "message_id": "ma", "error": "m: d"}
    ]


def test_unsupported_task_response_contract(backend, tasks, sqs_record, sqs_event):
    result = lambda_handler(
        sqs_event(sqs_record(task_name="nope", task_id="n1", message_id="mn")), None
    )
    assert result["failed_tasks"] == [
        {"task_id": "n1", "message_id": "mn", "error": "Task 'nope' not supported"}
    ]


def test_backend_failure_response_contract(tasks, sqs_record, sqs_event):
    with patch.object(
        aws_lambda.TaskModel,
        "insert_task",
        side_effect=BackendException("Error inserting task b1", "down"),
    ):
        result = lambda_handler(sqs_event(sqs_record(task_id="b1", message_id="mb")), None)

    assert result["failed_tasks"] == [
        {"task_id": "b1", "message_id": "mb", "error": "Error inserting task b1: down"}
    ]


def test_general_error_response_contract():
    with patch.object(
        aws_lambda.SQSEvent, "from_lambda", side_effect=Exception("Unexpected crash")
    ):
        result = lambda_handler({}, None)
    assert result["message"] == "General error: Unexpected crash"
    assert result["details"] == "Unexpected crash"


@pytest.mark.parametrize(
    "error,expected_detail",
    [
        (aws_lambda.TaskExecutionException("inner", "why"), "inner: why"),
        (aws_lambda.TaskExecutionException("inner"), "inner"),
        (RuntimeError("Boom"), "Boom"),
    ],
)
def test_call_task_error_contract(error, expected_detail):
    from celery_cloud.entities import Task

    with (
        patch.object(aws_lambda.settings, "TASKS", {"my.task": "task://m/f"}),
        patch.object(aws_lambda.TaskExecutor, "execute", side_effect=error),
    ):
        with pytest.raises(aws_lambda.TaskExecutionException) as exc:
            aws_lambda.call_task(Task(id="abc", task="my.task", args=[], kwargs={}))

    assert exc.value.message == "Exception executing task abc"
    assert exc.value.detail == expected_detail


def test_traceback_stored_for_a_failed_task_is_the_full_python_traceback(
    backend, tasks, sqs_record, sqs_event
):
    import traceback as tb

    _, update = backend
    error = RuntimeError("boom")

    def fail(task, *_):
        raise error

    with patch.object(aws_lambda, "call_task", side_effect=fail):
        lambda_handler(sqs_event(sqs_record()), None)

    stored = update.call_args.kwargs["traceback"]
    assert stored == "".join(tb.format_exception(type(error), error, error.__traceback__))
    assert "XXXX" not in stored


def test_record_failure_never_raises_when_the_backend_is_down(sqs_record):
    from celery_cloud.entities import Task

    task = Task(id="t", task="a.b", args=[], kwargs={})
    with (
        patch.object(aws_lambda.TaskModel, "update_task", side_effect=BackendException("x")),
        patch.object(aws_lambda, "logger") as logger,
    ):
        aws_lambda._record_failure(task, RuntimeError("boom"))
    assert "t" in logger.error.call_args.args[0]
    assert "FAILURE" in logger.error.call_args.args[0]


def test_failure_before_the_task_is_known_has_no_task_id(tasks, sqs_record, sqs_event):
    """Decode-time failures of every kind report task_id=None and store nothing."""
    for error in (
        aws_lambda.TaskDecodeException("bad"),
        BackendException("Error inserting task x"),
        RuntimeError("boom"),
    ):
        with (
            patch.object(aws_lambda.SQSMessage, "from_record", side_effect=error),
            patch.object(aws_lambda.TaskModel, "update_task") as update,
        ):
            result = lambda_handler(sqs_event(sqs_record(message_id="m-x")), None)

        failed = result["failed_tasks"][0]
        assert failed["task_id"] is None, type(error).__name__
        assert failed["message_id"] == "m-x"
        update.assert_not_called()
