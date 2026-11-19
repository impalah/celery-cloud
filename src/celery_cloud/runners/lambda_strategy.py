import json
import re
import threading
from functools import cache
from typing import Any

import boto3
import pybreaker
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from celery_cloud.entities import Task, TaskRoute
from celery_cloud.exceptions import TaskExecutionException
from celery_cloud.runners.task_execution_strategy import TaskExecutionStrategy
from celery_cloud.settings import settings

_LAMBDA_ARN_RE = re.compile(
    r"^arn:aws[a-z-]*:lambda:(?P<region>[a-z0-9-]+):\d{12}:function:[A-Za-z0-9_-]+"
    r"(:[A-Za-z0-9$_-]+)?$"
)


class LambdaFunctionError(TaskExecutionException):
    """The remote function ran and reported an error.

    It is neither retried (the code already executed and may have side
    effects) nor counted by the circuit breaker (it is a business error, not
    an infrastructure failure).
    """


class LambdaInvocationError(TaskExecutionException):
    """The remote function could not be invoked (throttling, network...).

    It is safe to retry: the function did not run.
    """


# One circuit breaker per remote function: a failing function must not open the
# circuit of the other ones.
_breakers: dict[str, pybreaker.CircuitBreaker] = {}
_breakers_lock = threading.Lock()


def get_breaker(function_arn: str) -> pybreaker.CircuitBreaker:
    """Get (or create) the circuit breaker of a remote function."""
    with _breakers_lock:
        breaker = _breakers.get(function_arn)
        if breaker is None:
            breaker = pybreaker.CircuitBreaker(
                fail_max=settings.CB_FAIL_MAX,
                reset_timeout=settings.CB_RESET_TIMEOUT,
                exclude=[LambdaFunctionError],
                name=function_arn,
            )
            _breakers[function_arn] = breaker
        return breaker


@cache
def _get_lambda_client(region: str) -> Any:
    """Get a cached boto3 lambda client for a region.

    botocore's own retries are disabled: the retry policy lives in one place
    (tenacity) and a read timeout must never silently re-invoke a function that
    may still be running.
    """
    return boto3.client(
        "lambda",
        region_name=region,
        config=Config(
            read_timeout=settings.LAMBDA_INVOKE_TIMEOUT,
            retries={"max_attempts": 0},
        ),
    )


class LambdaTaskExecutionStrategy(TaskExecutionStrategy):
    @retry(
        stop=stop_after_attempt(settings.MAX_ATTEMPTS),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(LambdaInvocationError),
        reraise=True,
    )
    def _invoke_lambda(self, lambda_client: Any, task: Task, route: TaskRoute) -> Any:
        try:
            response = lambda_client.invoke(
                FunctionName=route.module,
                InvocationType="RequestResponse",
                Payload=json.dumps({"args": task.args, "kwargs": task.kwargs}),
            )
        except (ClientError, BotoCoreError) as e:
            raise LambdaInvocationError(
                message=f"Could not invoke Lambda function {route.module}",
                detail=str(e),
            ) from e

        response_payload = json.loads(response["Payload"].read())

        if "FunctionError" in response:
            raise LambdaFunctionError(
                message=f"Lambda function {route.module} returned an error",
                detail=json.dumps(response_payload),
            )

        if isinstance(response_payload, dict):
            return response_payload.get("body", response_payload)
        return response_payload

    def execute(self, task: Task, route: TaskRoute) -> Any:
        match = _LAMBDA_ARN_RE.match(route.module)
        if match is None:
            raise TaskExecutionException(
                message=f"Invalid Lambda function ARN for task {task.task}",
                detail=route.module,
            )

        lambda_client = _get_lambda_client(match.group("region"))
        breaker = get_breaker(route.module)

        try:
            # The breaker wraps the whole retried invocation: it counts one
            # failure per exhausted invocation, not per attempt.
            return breaker.call(self._invoke_lambda, lambda_client, task, route)

        except pybreaker.CircuitBreakerError as e:
            raise TaskExecutionException(
                message=f"Circuit breaker open for Lambda function {route.module}",
                detail=str(e),
            ) from e

        except TaskExecutionException:
            raise

        except Exception as e:
            raise TaskExecutionException(
                message=f"Unexpected error calling Lambda function {route.module}",
                detail=str(e),
            ) from e
