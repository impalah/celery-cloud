import json
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from celery_cloud.entities import Task, TaskRoute
from celery_cloud.exceptions import TaskExecutionException
from celery_cloud.runners import lambda_strategy
from celery_cloud.runners.lambda_strategy import (
    LambdaFunctionError,
    LambdaTaskExecutionStrategy,
    get_breaker,
)

ARN = "arn:aws:lambda:us-east-1:123456789012:function:test-fn"


def make_route(arn: str = ARN) -> TaskRoute:
    return TaskRoute(scheme="lambda", module=arn, function="", query={})


def make_response(payload, function_error: str | None = None):
    response = {"Payload": MagicMock(read=lambda: json.dumps(payload).encode())}
    if function_error:
        response["FunctionError"] = function_error
    return response


@pytest.fixture(autouse=True)
def clean_state():
    lambda_strategy._breakers.clear()
    lambda_strategy._get_lambda_client.cache_clear()
    with patch("tenacity.nap.time.sleep"):  # do not really wait between retries
        yield
    lambda_strategy._breakers.clear()
    lambda_strategy._get_lambda_client.cache_clear()


@pytest.fixture
def task():
    return Task(id="abc", task="t", args=["x"], kwargs={"y": 1})


@pytest.fixture
def lambda_client():
    with patch.object(lambda_strategy.boto3, "client") as client_factory:
        client = MagicMock()
        client_factory.return_value = client
        client.factory = client_factory
        yield client


def throttling_error():
    return ClientError(
        {"Error": {"Code": "TooManyRequestsException", "Message": "slow"}}, "Invoke"
    )


def test_success_unwraps_body(task, lambda_client):
    lambda_client.invoke.return_value = make_response({"body": "ok"})

    assert LambdaTaskExecutionStrategy().execute(task, make_route()) == "ok"

    kwargs = lambda_client.invoke.call_args.kwargs
    assert kwargs["FunctionName"] == ARN
    assert json.loads(kwargs["Payload"]) == {"args": ["x"], "kwargs": {"y": 1}}


def test_success_without_body_key_returns_payload(task, lambda_client):
    lambda_client.invoke.return_value = make_response([1, 2, 3])

    assert LambdaTaskExecutionStrategy().execute(task, make_route()) == [1, 2, 3]


def test_client_is_cached_per_region_with_safe_config(task, lambda_client):
    lambda_client.invoke.return_value = make_response({"body": 1})
    strategy = LambdaTaskExecutionStrategy()

    strategy.execute(task, make_route())
    strategy.execute(task, make_route())

    lambda_client.factory.assert_called_once()
    config = lambda_client.factory.call_args.kwargs["config"]
    assert lambda_client.factory.call_args.kwargs["region_name"] == "us-east-1"
    assert config.retries["max_attempts"] == 0  # botocore must not re-invoke
    assert config.read_timeout == lambda_strategy.settings.LAMBDA_INVOKE_TIMEOUT


def test_function_error_is_not_retried_nor_counted_by_breaker(task, lambda_client):
    lambda_client.invoke.return_value = make_response({"error": "fail"}, "Handled")
    strategy = LambdaTaskExecutionStrategy()

    for _ in range(lambda_strategy.settings.CB_FAIL_MAX + 2):
        with pytest.raises(LambdaFunctionError) as exc:
            strategy.execute(task, make_route())

    assert "returned an error" in exc.value.message
    # one invocation per call: the function already ran, never re-run it
    assert lambda_client.invoke.call_count == lambda_strategy.settings.CB_FAIL_MAX + 2
    assert get_breaker(ARN).current_state == "closed"


def test_invocation_errors_are_retried_then_raised(task, lambda_client):
    lambda_client.invoke.side_effect = throttling_error()

    with pytest.raises(TaskExecutionException) as exc:
        LambdaTaskExecutionStrategy().execute(task, make_route())

    assert "Could not invoke Lambda function" in exc.value.message
    assert lambda_client.invoke.call_count == lambda_strategy.settings.MAX_ATTEMPTS


def test_invocation_error_recovers(task, lambda_client):
    lambda_client.invoke.side_effect = [
        throttling_error(),
        make_response({"body": "ok"}),
    ]

    assert LambdaTaskExecutionStrategy().execute(task, make_route()) == "ok"
    assert lambda_client.invoke.call_count == 2


def test_circuit_breaker_opens_per_function(task, lambda_client):
    lambda_client.invoke.side_effect = throttling_error()
    strategy = LambdaTaskExecutionStrategy()

    for _ in range(lambda_strategy.settings.CB_FAIL_MAX):
        with pytest.raises(TaskExecutionException):
            strategy.execute(task, make_route())

    calls = lambda_client.invoke.call_count
    with pytest.raises(TaskExecutionException) as exc:
        strategy.execute(task, make_route())
    assert "Circuit breaker open" in exc.value.message
    assert lambda_client.invoke.call_count == calls  # circuit open: no invocation

    # A different function is not affected
    other = "arn:aws:lambda:us-east-1:123456789012:function:other-fn"
    lambda_client.invoke.side_effect = None
    lambda_client.invoke.return_value = make_response({"body": "fine"})
    assert strategy.execute(task, make_route(other)) == "fine"


def test_unexpected_error_is_wrapped(task, lambda_client):
    lambda_client.invoke.return_value = {
        "Payload": MagicMock(read=lambda: b"not json")
    }

    with pytest.raises(TaskExecutionException) as exc:
        LambdaTaskExecutionStrategy().execute(task, make_route())

    assert "Unexpected error calling Lambda function" in exc.value.message


@pytest.mark.parametrize(
    "arn", ["", "not-an-arn", "arn:aws:lambda:us-east-1:123:function:x", "lambda"]
)
def test_invalid_arn_is_rejected(task, arn):
    with pytest.raises(TaskExecutionException) as exc:
        LambdaTaskExecutionStrategy().execute(task, make_route(arn))
    assert "Invalid Lambda function ARN" in exc.value.message


def test_arn_with_alias_is_accepted(task, lambda_client):
    lambda_client.invoke.return_value = make_response({"body": 1})
    arn = ARN + ":prod"
    assert LambdaTaskExecutionStrategy().execute(task, make_route(arn)) == 1


# ---- exact contracts --------------------------------------------------------


def test_breaker_uses_the_configured_values():
    # not the pybreaker defaults (5 / 60), so ignoring the settings is detected
    with (
        patch.object(lambda_strategy.settings, "CB_FAIL_MAX", 7),
        patch.object(lambda_strategy.settings, "CB_RESET_TIMEOUT", 13),
    ):
        breaker = get_breaker(ARN)
    assert breaker.fail_max == 7
    assert breaker.reset_timeout == 13
    assert breaker.name == ARN
    assert get_breaker(ARN) is breaker  # one breaker per function, reused


def test_invalid_arn_detail_is_the_arn(task):
    with pytest.raises(TaskExecutionException) as exc:
        LambdaTaskExecutionStrategy().execute(task, make_route("nonsense"))
    assert exc.value.message == "Invalid Lambda function ARN for task t"
    assert exc.value.detail == "nonsense"


def test_invocation_error_detail_has_the_cause(task, lambda_client):
    lambda_client.invoke.side_effect = throttling_error()
    with pytest.raises(TaskExecutionException) as exc:
        LambdaTaskExecutionStrategy().execute(task, make_route())
    assert exc.value.message == f"Could not invoke Lambda function {ARN}"
    assert "TooManyRequestsException" in exc.value.detail


def test_function_error_detail_is_the_remote_payload(task, lambda_client):
    lambda_client.invoke.return_value = make_response({"errorMessage": "bad"}, "Unhandled")
    with pytest.raises(LambdaFunctionError) as exc:
        LambdaTaskExecutionStrategy().execute(task, make_route())
    assert json.loads(exc.value.detail) == {"errorMessage": "bad"}


def test_unexpected_error_detail_is_the_cause(task, lambda_client):
    lambda_client.invoke.return_value = {"Payload": MagicMock(read=lambda: b"not json")}
    with pytest.raises(TaskExecutionException) as exc:
        LambdaTaskExecutionStrategy().execute(task, make_route())
    assert exc.value.message == f"Unexpected error calling Lambda function {ARN}"
    assert "Expecting value" in exc.value.detail


def test_open_circuit_error_contract(task, lambda_client):
    lambda_client.invoke.side_effect = throttling_error()
    strategy = LambdaTaskExecutionStrategy()
    for _ in range(lambda_strategy.settings.CB_FAIL_MAX):
        with pytest.raises(TaskExecutionException):
            strategy.execute(task, make_route())
    with pytest.raises(TaskExecutionException) as exc:
        strategy.execute(task, make_route())
    assert exc.value.message == f"Circuit breaker open for Lambda function {ARN}"
    assert "circuit" in exc.value.detail.lower()
