"""Original exceptions, time limits, Lambda deadline and extended meta (moto)."""

import base64
import json
import sys
import time
import types
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from celery_cloud import task
from celery_cloud.models.task_model import TaskModel
from celery_cloud.runners import aws_lambda
from celery_cloud.runners.aws_lambda import lambda_handler
from celery_cloud.runners.lambda_strategy import LambdaFunctionError
from sqs_helpers import build_sqs_record


class InsufficientFunds(Exception):
    """A user exception, defined in a module the client does not import."""


class Context:
    def __init__(self, millis):
        self.millis = millis

    def get_remaining_time_in_millis(self):
        return self.millis


@task(soft_time_limit=0.2)
def decorated_soft(a=0):
    time.sleep(5)


@task(time_limit=0.2)
def decorated_hard(a=0):
    time.sleep(5)


@pytest.fixture
def tasks():
    module = types.ModuleType("limit_tasks")

    def slow(args, kwargs):
        time.sleep(5)
        return "never"

    def slow_but_catches_soft(args, kwargs):
        try:
            time.sleep(5)
        except Exception:
            return "cleaned up"

    def withdraw(args, kwargs):
        raise InsufficientFunds("balance", 3, 10)

    def not_json(args, kwargs):
        raise ValueError(object, {1, 2})

    def silent(args, kwargs):
        raise KeyError()

    module.slow = slow  # type: ignore[attr-defined]
    module.slow_but_catches_soft = slow_but_catches_soft  # type: ignore[attr-defined]
    module.withdraw = withdraw  # type: ignore[attr-defined]
    module.not_json = not_json  # type: ignore[attr-defined]
    module.silent = silent  # type: ignore[attr-defined]
    module.ok = lambda args, kwargs: sum(args)  # type: ignore[attr-defined]
    module.decorated_soft = decorated_soft  # type: ignore[attr-defined]
    module.decorated_hard = decorated_hard  # type: ignore[attr-defined]
    sys.modules["limit_tasks"] = module
    routes = {
        f"t.{name}": f"task://limit_tasks/{name}"
        for name in (
            "slow", "slow_but_catches_soft", "withdraw", "not_json", "silent", "ok",
            "decorated_soft", "decorated_hard",
        )
    }
    with patch.object(aws_lambda.settings, "TASKS", routes):
        yield
    del sys.modules["limit_tasks"]


def run(*records, context=None):
    return lambda_handler({"Records": list(records)}, context)


def stored(task_id):
    return TaskModel.get_task(task_id)["result"]


# -- the client receives the ORIGINAL exception -------------------------------


def test_a_custom_exception_is_reported_with_its_own_type_and_args(tasks):
    run(build_sqs_record("t.withdraw", "w1"))
    assert stored("w1")["result"] == {
        "exc_type": "InsufficientFunds",
        "exc_message": ["balance", 3, 10],
        "exc_module": __name__,
    }


def test_arguments_that_json_cannot_hold_are_stored_as_text(tasks):
    run(build_sqs_record("t.not_json", "j1"))
    payload = stored("j1")["result"]
    assert payload["exc_type"] == "ValueError"
    assert len(payload["exc_message"]) == 2
    assert all(isinstance(part, str) for part in payload["exc_message"])


def test_an_exception_without_arguments_has_no_message(tasks):
    run(build_sqs_record("t.silent", "k1"))
    assert stored("k1")["result"]["exc_message"] == []


def test_a_remote_lambda_error_keeps_the_remote_exception_type():
    error = LambdaFunctionError(
        message="Lambda function f returned an error",
        detail=json.dumps({"errorMessage": "bad input", "errorType": "ValueError"}),
    )
    assert aws_lambda._failure_payload(error) == {
        "exc_type": "ValueError",
        "exc_message": ["bad input"],
        "exc_module": "builtins",
    }


def test_a_remote_lambda_error_with_a_custom_type_has_no_importable_module():
    error = LambdaFunctionError(
        message="m", detail=json.dumps({"errorMessage": "x", "errorType": "PaymentError"})
    )
    assert aws_lambda._failure_payload(error) == {
        "exc_type": "PaymentError",
        "exc_message": ["x"],
        "exc_module": "remote_lambda",
    }


@pytest.mark.parametrize("detail", ["not json", "[1, 2]", ""])
def test_a_remote_lambda_error_without_a_usable_document(detail):
    error = LambdaFunctionError(message="remote failed", detail=detail)
    assert aws_lambda._failure_payload(error) == {
        "exc_type": "LambdaFunctionError",
        "exc_message": ["remote failed"],
        "exc_module": "remote_lambda",
    }


def test_a_remote_error_type_that_is_not_an_exception_is_not_builtins():
    error = LambdaFunctionError(
        message="m", detail=json.dumps({"errorMessage": "x", "errorType": "print"})
    )
    assert aws_lambda._failure_payload(error)["exc_module"] == "remote_lambda"


def test_an_exception_with_only_a_custom_str_uses_it_as_message():
    class Odd(Exception):
        def __str__(self):
            return "custom text"

    assert aws_lambda._failure_payload(Odd())["exc_message"] == ["custom text"]


# -- time limits of the message -----------------------------------------------


def test_the_soft_time_limit_of_the_message_stops_the_task(tasks):
    started = time.monotonic()
    result = run(build_sqs_record("t.slow", "s1", timelimit=[None, 0.2]))

    assert time.monotonic() - started < 3
    assert result["failed_messages"] == 1
    meta = stored("s1")
    assert meta["status"] == "FAILURE"
    assert meta["result"] == {
        "exc_type": "SoftTimeLimitExceeded",
        "exc_message": ["SoftTimeLimitExceeded(0.2,)"],
        # Celery rebuilds celery.exceptions.SoftTimeLimitExceeded on the client
        "exc_module": "celery.exceptions",
    }


def test_the_hard_time_limit_of_the_message_stops_the_task(tasks):
    run(build_sqs_record("t.slow", "h1", timelimit=[0.2, None]))
    assert stored("h1")["result"]["exc_type"] == "TimeLimitExceeded"
    assert stored("h1")["result"]["exc_module"] == "celery.exceptions"


def test_a_task_that_handles_the_soft_limit_can_still_succeed(tasks):
    run(build_sqs_record("t.slow_but_catches_soft", "c1", timelimit=[None, 0.2]))
    assert stored("c1")["status"] == "SUCCESS"
    assert stored("c1")["result"] == "cleaned up"


def test_the_limits_of_the_task_decorator_apply(tasks):
    started = time.monotonic()
    run(build_sqs_record("t.decorated_soft", "dd1"))
    run(build_sqs_record("t.decorated_hard", "dd2"))

    assert time.monotonic() - started < 3
    assert stored("dd1")["result"]["exc_type"] == "SoftTimeLimitExceeded"
    assert stored("dd2")["result"]["exc_type"] == "TimeLimitExceeded"


def test_the_limits_of_the_message_win_over_the_decorator(tasks):
    """The decorator says 0.2 s, the client asks for 0.6 s: the client wins."""
    started = time.monotonic()
    run(build_sqs_record("t.decorated_soft", "dd3", timelimit=[None, 0.6]))
    elapsed = time.monotonic() - started
    assert 0.5 < elapsed < 3
    assert stored("dd3")["result"]["exc_message"] == ["SoftTimeLimitExceeded(0.6,)"]


def test_a_function_that_cannot_be_imported_reports_the_real_error(tasks):
    with patch.object(
        aws_lambda.settings, "TASKS", {"t.ghost": "task://no_such_module/fn"}
    ):
        run(build_sqs_record("t.ghost", "dd4"))
    assert stored("dd4")["result"]["exc_type"] == "ModuleNotFoundError"


# -- the Lambda deadline ------------------------------------------------------


def test_the_function_is_stopped_before_aws_kills_it(tasks):
    """10.4 s left, 10 s of margin: 0.4 s budget instead of a stuck STARTED task."""
    started = time.monotonic()
    result = run(build_sqs_record("t.slow", "d1"), context=Context(10_400))

    assert time.monotonic() - started < 3
    assert result["failed_messages"] == 1
    assert result["batchItemFailures"] == []
    meta = stored("d1")
    assert meta["status"] == "FAILURE"  # not STARTED forever
    assert meta["result"]["exc_type"] == "TimeLimitExceeded"
    assert "about to reach its timeout" in meta["result"]["exc_message"][0]


def test_a_task_that_fits_in_the_remaining_time_runs_normally(tasks):
    run(build_sqs_record("t.ok", "f1", args=[1, 2]), context=Context(60_000))
    assert stored("f1")["result"] == 3


def test_records_that_cannot_start_in_time_go_back_to_sqs(tasks):
    result = run(
        build_sqs_record("t.ok", "n1", args=[1], message_id="mA"),
        build_sqs_record("t.ok", "n2", args=[2], message_id="mB"),
        context=Context(9_000),  # less than the 10 s margin
    )

    assert result["processed_messages"] == 0
    assert result["failed_messages"] == 2
    assert result["batchItemFailures"] == [
        {"itemIdentifier": "mA"},
        {"itemIdentifier": "mB"},
    ]
    assert result["failed_tasks"][0]["error"] == (
        "Not started: the Lambda function is about to time out"
    )
    # nothing was registered: the redelivery will be processed normally
    assert TaskModel.get_task("n1") is None


def test_the_batch_stops_starting_tasks_as_time_runs_out(tasks):
    """The first task consumes the budget; the second one is returned to SQS."""
    now = [0.0]  # fake clock of the handler, in seconds

    def first_task_takes_five_seconds(task, *_):
        now[0] += 5
        return "done"

    with (
        patch.object(aws_lambda, "time", SimpleNamespace(monotonic=lambda: now[0], perf_counter=time.perf_counter)),
        patch.object(aws_lambda, "call_task", side_effect=first_task_takes_five_seconds),
    ):
        # 11.5 s left: the first record starts (1.5 s above the 10 s margin);
        # after it only 6.5 s are left, below the margin
        result = run(
            build_sqs_record("t.ok", "b1", args=[1], message_id="m1"),
            build_sqs_record("t.ok", "b2", args=[2], message_id="m2"),
            context=Context(11_500),
        )

    assert [t["task_id"] for t in result["processed_tasks"]] == ["b1"]
    assert result["batchItemFailures"] == [{"itemIdentifier": "m2"}]
    assert TaskModel.get_task("b2") is None


def test_no_margin_means_everything_starts_while_there_is_time(tasks, monkeypatch):
    monkeypatch.setattr(aws_lambda.settings, "TIMEOUT_MARGIN_SECONDS", 0)
    result = run(build_sqs_record("t.ok", "z1", args=[4]), context=Context(500))
    assert result["processed_messages"] == 1


def test_the_error_of_a_record_that_could_not_start_is_not_stored(tasks):
    run(build_sqs_record("t.ok", "q1"), context=Context(1_000))
    assert TaskModel.get_task("q1") is None


# -- extended meta ------------------------------------------------------------


def test_extended_meta_is_stored_when_enabled(tasks, monkeypatch):
    monkeypatch.setattr(aws_lambda.settings, "RESULT_EXTENDED", True)
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "my-runner")
    run(build_sqs_record("t.ok", "e1", args=[1, 2], kwargs={"k": 1}))

    meta = stored("e1")
    assert meta["status"] == "SUCCESS"
    assert meta["name"] == "t.ok"
    assert meta["args"] == [1, 2]
    assert meta["kwargs"] == {"k": 1}
    assert meta["worker"] == "my-runner"
    assert meta["retries"] == 0
    assert meta["queue"] == "my-queue"


def test_extended_meta_is_also_stored_for_failures(tasks, monkeypatch):
    monkeypatch.setattr(aws_lambda.settings, "RESULT_EXTENDED", True)
    run(build_sqs_record("t.withdraw", "e2", args=[5]))
    meta = stored("e2")
    assert meta["status"] == "FAILURE"
    assert meta["name"] == "t.withdraw"
    assert meta["args"] == [5]


def test_extended_meta_is_absent_by_default(tasks):
    run(build_sqs_record("t.ok", "e3", args=[1]))
    meta = stored("e3")
    for key in ("name", "args", "kwargs", "worker", "retries", "queue"):
        assert key not in meta


# -- groups -------------------------------------------------------------------


def test_the_tasks_of_a_group_are_independent_messages(tasks):
    records = []
    for index, value in enumerate([1, 2, 3]):
        record = build_sqs_record(
            "t.ok", f"g{index}", args=[value], message_id=f"mg{index}"
        )
        # a group member carries the group id and its index in the headers
        envelope = json.loads(base64.b64decode(record["body"]))
        envelope["headers"]["group"] = "group-1"
        envelope["headers"]["group_index"] = index
        record["body"] = base64.b64encode(
            json.dumps(envelope).encode()
        ).decode()
        records.append(record)

    result = run(*records)

    assert result["processed_messages"] == 3
    assert [stored(f"g{i}")["result"] for i in range(3)] == [1, 2, 3]
