import random
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

import celery_cloud
from celery_cloud import (
    Ignore,
    MaxRetriesExceededError,
    Reject,
    Retry,
    TaskContext,
    TaskOptions,
    TaskRequest,
    task,
)
from celery_cloud.runtime import reset_runtime, set_runtime
from celery_cloud.tasks import backoff_countdown, call_task_function, get_options


def request(**overrides):
    values = {"id": "t-1", "task": "my.task", "args": [1, 2], "kwargs": {"k": 3}}
    values.update(overrides)
    return TaskRequest(**values)


# -- the decorator -------------------------------------------------------------


def test_defaults_match_celery():
    options = TaskOptions()
    assert options.max_retries == 3
    assert options.default_retry_delay == 180
    assert options.autoretry_for == ()
    assert options.retry_backoff is False
    assert options.retry_backoff_max == 600
    assert options.retry_jitter is True
    assert options.bind is False


def test_task_without_arguments():
    @task
    def add(x, y):
        return x + y

    assert add(1, 2) == 3  # still directly callable
    assert get_options(add) == TaskOptions()


def test_task_with_options():
    @task(bind=True, max_retries=7, default_retry_delay=5, soft_time_limit=30)
    def work(self):
        return self

    options = get_options(work)
    assert options.bind is True
    assert (options.max_retries, options.default_retry_delay) == (7, 5)
    assert options.soft_time_limit == 30


def test_unknown_option_is_rejected():
    with pytest.raises(TypeError):
        task(bogus=True)


def test_a_plain_function_has_no_options():
    assert get_options(lambda args, kwargs: 1) is None


def test_the_package_exports_the_public_api():
    for name in ("task", "Retry", "Ignore", "Reject", "SoftTimeLimitExceeded"):
        assert hasattr(celery_cloud, name)


# -- TaskContext ---------------------------------------------------------------


def context(**options):
    return TaskContext(request(), TaskOptions(**options))


def test_context_exposes_the_request_and_name():
    ctx = context(max_retries=9)
    assert ctx.request.id == "t-1"
    assert ctx.name == "my.task"
    assert ctx.max_retries == 9


def test_retry_uses_the_default_delay():
    with pytest.raises(Retry) as raised:
        context(default_retry_delay=42).retry()
    assert raised.value.countdown == 42
    assert raised.value.eta is None
    assert raised.value.exc is None


def test_retry_with_a_countdown_and_the_causing_exception():
    cause = ConnectionError("down")
    with pytest.raises(Retry) as raised:
        context().retry(exc=cause, countdown=7)
    assert raised.value.countdown == 7
    assert raised.value.exc is cause
    assert "ConnectionError" in str(raised.value)


def test_retry_with_an_eta_does_not_add_a_countdown():
    eta = datetime(2030, 1, 1, tzinfo=UTC)
    with pytest.raises(Retry) as raised:
        context().retry(eta=eta)
    assert raised.value.eta == eta
    assert raised.value.countdown is None


def test_retry_beyond_max_retries_raises_the_original_exception():
    ctx = TaskContext(request(retries=3), TaskOptions(max_retries=3))
    cause = ConnectionError("still down")
    with pytest.raises(ConnectionError) as raised:
        ctx.retry(exc=cause)
    assert raised.value is cause


def test_retry_beyond_max_retries_without_exception():
    ctx = TaskContext(request(retries=3), TaskOptions(max_retries=3))
    with pytest.raises(MaxRetriesExceededError) as raised:
        ctx.retry()
    assert str(raised.value) == (
        "Can't retry my.task[t-1] args:[1, 2] kwargs:{'k': 3}"
    )


def test_retry_max_retries_can_be_overridden_per_call():
    ctx = TaskContext(request(retries=1), TaskOptions(max_retries=10))
    with pytest.raises(MaxRetriesExceededError):
        ctx.retry(max_retries=1)


def test_retry_without_a_limit_never_gives_up():
    ctx = TaskContext(request(retries=10_000), TaskOptions(max_retries=None))
    with pytest.raises(Retry):
        ctx.retry()


def test_retry_ignores_celery_options_it_does_not_know():
    with pytest.raises(Retry):
        context().retry(queue="other", priority=3)


class FakeRuntime:
    def __init__(self, revoked=False):
        self.calls = []
        self.revoked = revoked

    def update_state(self, task_id, state, meta):
        self.calls.append((task_id, state, meta))

    def is_revoked(self, task_id):
        self.calls.append(("revoked?", task_id))
        return self.revoked


def test_update_state_goes_to_the_runtime():
    runtime = FakeRuntime()
    token = set_runtime(runtime)
    try:
        context().update_state(state="PROGRESS", meta={"done": 1})
        context().update_state("other-id", "PROGRESS", 5)
    finally:
        reset_runtime(token)
    assert runtime.calls == [
        ("t-1", "PROGRESS", {"done": 1}),
        ("other-id", "PROGRESS", 5),
    ]


def test_update_state_outside_the_runner_does_nothing():
    context().update_state(state="PROGRESS", meta=1)  # no error


def test_update_state_without_a_state_does_nothing():
    runtime = FakeRuntime()
    token = set_runtime(runtime)
    try:
        context().update_state(meta={"a": 1})
    finally:
        reset_runtime(token)
    assert runtime.calls == []


def test_is_revoked_asks_the_runtime():
    token = set_runtime(FakeRuntime(revoked=True))
    try:
        assert context().is_revoked() is True
    finally:
        reset_runtime(token)
    assert context().is_revoked() is False  # outside the runner


# -- backoff -------------------------------------------------------------------


def test_without_backoff_the_default_delay_is_used():
    assert backoff_countdown(TaskOptions(default_retry_delay=30), 4) == 30


@pytest.mark.parametrize("retries,expected", [(0, 1), (1, 2), (2, 4), (5, 32)])
def test_exponential_backoff_doubles(retries, expected):
    options = TaskOptions(retry_backoff=True, retry_jitter=False)
    assert backoff_countdown(options, retries) == expected


def test_backoff_factor_and_maximum():
    options = TaskOptions(retry_backoff=3, retry_backoff_max=20, retry_jitter=False)
    assert backoff_countdown(options, 1) == 6
    assert backoff_countdown(options, 10) == 20


def test_jitter_picks_a_value_between_zero_and_the_backoff():
    options = TaskOptions(retry_backoff=True, retry_jitter=True)
    with patch.object(random, "randrange", return_value=3) as pick:
        assert backoff_countdown(options, 2) == 3
    pick.assert_called_once_with(5)  # 4 s of backoff -> randrange(4 + 1)


# -- calling the function ------------------------------------------------------


def test_a_plain_function_gets_args_and_kwargs():
    def legacy(args, kwargs):
        return (args, kwargs)

    assert call_task_function(legacy, request()) == ([1, 2], {"k": 3})


def test_a_decorated_function_gets_natural_arguments():
    @task
    def natural(a, b, k=0):
        return a + b + k

    assert call_task_function(natural, request()) == 6


def test_a_bound_function_gets_the_context():
    @task(bind=True)
    def bound(self, a, b, k=0):
        return (self.request.id, a + b + k)

    assert call_task_function(bound, request()) == ("t-1", 6)


@pytest.mark.parametrize("control", [Retry(), Ignore(), Reject("no")])
def test_control_exceptions_pass_through(control):
    @task(autoretry_for=(Exception,))
    def raises():
        raise control

    with pytest.raises(type(control)) as raised:
        call_task_function(raises, request(args=[], kwargs={}))
    assert raised.value is control


def test_autoretry_turns_listed_exceptions_into_a_retry():
    @task(autoretry_for=(ConnectionError,), default_retry_delay=11)
    def flaky():
        raise ConnectionError("down")

    with pytest.raises(Retry) as raised:
        call_task_function(flaky, request(args=[], kwargs={}))
    assert raised.value.countdown == 11
    assert isinstance(raised.value.exc, ConnectionError)


def test_autoretry_uses_the_backoff_of_the_current_attempt():
    @task(
        autoretry_for=(ConnectionError,),
        retry_backoff=True,
        retry_jitter=False,
    )
    def flaky():
        raise ConnectionError("down")

    with pytest.raises(Retry) as raised:
        call_task_function(flaky, request(args=[], kwargs={}, retries=2))
    assert raised.value.countdown == 4


def test_autoretry_gives_up_with_the_original_error_when_retries_run_out():
    @task(autoretry_for=(ConnectionError,), max_retries=2)
    def flaky():
        raise ConnectionError("down")

    with pytest.raises(ConnectionError, match="down"):
        call_task_function(flaky, request(args=[], kwargs={}, retries=2))


def test_exceptions_that_are_not_listed_are_not_retried():
    @task(autoretry_for=(ConnectionError,))
    def broken():
        raise ValueError("bug")

    with pytest.raises(ValueError):
        call_task_function(broken, request(args=[], kwargs={}))


def test_a_mock_function_is_treated_as_plain():
    assert get_options(MagicMock()) is None
