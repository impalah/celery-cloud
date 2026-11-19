import pytest

from celery_cloud import Ignore, Reject, Retry, TaskRequest, task
from celery_cloud.tasks import call_task_function


def request(**overrides):
    values = {"id": "t-1", "task": "my.task", "args": [1], "kwargs": {"k": 2}}
    values.update(overrides)
    return TaskRequest(**values)


class Recorder:
    def __init__(self):
        self.calls = []

    def on_success(self, retval, task_id, args, kwargs):
        self.calls.append(("success", retval, task_id, args, kwargs))

    def on_failure(self, exc, task_id, args, kwargs, traceback):
        self.calls.append(("failure", type(exc).__name__, task_id, args, kwargs))
        self.traceback = traceback

    def on_retry(self, exc, task_id, args, kwargs, traceback):
        self.calls.append(("retry", type(exc).__name__, task_id, args, kwargs))


def test_on_success_gets_the_result():
    hooks = Recorder()

    @task(on_success=hooks.on_success)
    def ok(a, k=0):
        return a + k

    assert call_task_function(ok, request()) == 3
    assert hooks.calls == [("success", 3, "t-1", [1], {"k": 2})]


def test_on_failure_gets_the_exception_and_the_traceback_and_the_error_propagates():
    hooks = Recorder()

    @task(on_failure=hooks.on_failure)
    def broken(a, k=0):
        raise ValueError("bad")

    with pytest.raises(ValueError, match="bad"):
        call_task_function(broken, request())

    assert hooks.calls == [("failure", "ValueError", "t-1", [1], {"k": 2})]
    assert "ValueError: bad" in hooks.traceback


def test_on_retry_gets_the_exception_that_caused_the_retry():
    hooks = Recorder()

    @task(bind=True, on_retry=hooks.on_retry)
    def flaky(self, a, k=0):
        raise self.retry(exc=ConnectionError("down"))

    with pytest.raises(Retry):
        call_task_function(flaky, request())

    assert hooks.calls == [("retry", "ConnectionError", "t-1", [1], {"k": 2})]


def test_on_retry_for_a_retry_without_an_exception_gets_the_retry():
    hooks = Recorder()

    @task(bind=True, on_retry=hooks.on_retry)
    def flaky(self, a, k=0):
        raise self.retry()

    with pytest.raises(Retry):
        call_task_function(flaky, request())
    assert hooks.calls[0][:2] == ("retry", "Retry")


def test_autoretry_calls_on_retry_and_when_exhausted_on_failure():
    hooks = Recorder()

    @task(
        autoretry_for=(ConnectionError,),
        max_retries=1,
        on_retry=hooks.on_retry,
        on_failure=hooks.on_failure,
    )
    def flaky(a, k=0):
        raise ConnectionError("down")

    with pytest.raises(Retry):
        call_task_function(flaky, request(retries=0))
    with pytest.raises(ConnectionError):
        call_task_function(flaky, request(retries=1))

    assert [call[0] for call in hooks.calls] == ["retry", "failure"]


@pytest.mark.parametrize("control", [Ignore(), Reject("no")])
def test_ignore_and_reject_call_no_hook(control):
    hooks = Recorder()

    @task(on_success=hooks.on_success, on_failure=hooks.on_failure, on_retry=hooks.on_retry)
    def controlled(a, k=0):
        raise control

    with pytest.raises(type(control)):
        call_task_function(controlled, request())
    assert hooks.calls == []


def test_a_hook_that_fails_does_not_change_the_outcome(caplog):
    def bad_hook(*args):
        raise RuntimeError("hook bug")

    @task(on_success=bad_hook)
    def ok(a, k=0):
        return "fine"

    assert call_task_function(ok, request()) == "fine"
    assert "Hook" in caplog.text and "my.task" in caplog.text


def test_tasks_without_hooks_are_unaffected():
    @task
    def ok(a, k=0):
        return "fine"

    assert call_task_function(ok, request()) == "fine"
