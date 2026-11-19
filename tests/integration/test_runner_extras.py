"""Signals, metrics, init modules and batch concurrency inside the handler."""

import json
import sys
import threading
import time
import types
from unittest.mock import patch

import pytest

from celery_cloud import Ignore, Reject, signals, task
from celery_cloud.models.task_model import TaskModel
from celery_cloud.runners import aws_lambda
from celery_cloud.runners.aws_lambda import lambda_handler
from sqs_helpers import build_sqs_record

seen_threads: list[int] = []


@task
def add(x, y=0):
    return x + y


@task
def boom():
    raise ValueError("bad")


@task(bind=True, max_retries=2, default_retry_delay=0)
def retries(self):
    raise self.retry(exc=ConnectionError("down"))


@task
def ignores():
    raise Ignore()


@task
def rejects():
    raise Reject("no", requeue=False)


@task
def nap():
    seen_threads.append(threading.get_ident())
    time.sleep(0.4)
    return "rested"


@pytest.fixture
def extras(queue):
    module = types.ModuleType("extra_tasks")
    for function in (add, boom, retries, ignores, rejects, nap):
        setattr(module, function.__name__, function)
    sys.modules["extra_tasks"] = module
    routes = {f"t.{n}": f"task://extra_tasks/{n}" for n in (
        "add", "boom", "retries", "ignores", "rejects", "nap")}
    seen_threads.clear()
    with patch.object(aws_lambda.settings, "TASKS", routes):
        yield queue
    del sys.modules["extra_tasks"]


@pytest.fixture
def events():
    """Record every signal, in order."""
    log: list[tuple[str, dict]] = []
    receivers = {}
    for name in ("task_prerun", "task_postrun", "task_success", "task_failure", "task_retry"):
        signal = getattr(signals, name)

        def receiver(_name=name, **kwargs):
            log.append((_name, kwargs))

        receivers[name] = signal.connect(receiver)
    yield log
    for name, receiver in receivers.items():
        getattr(signals, name).disconnect(receiver)


def run(*records, context=None):
    return lambda_handler({"Records": list(records)}, context)


# -- signals --------------------------------------------------------------------


def test_signals_around_a_successful_task(extras, events):
    run(build_sqs_record("t.add", "s1", args=[2, 3]))

    assert [name for name, _ in events] == ["task_prerun", "task_success", "task_postrun"]
    prerun, success, postrun = (kwargs for _, kwargs in events)
    assert prerun == {"task_id": "s1", "task": "t.add", "args": [2, 3], "kwargs": {}}
    assert success == {"task_id": "s1", "task": "t.add", "result": 5}
    assert postrun["state"] == "SUCCESS" and postrun["retval"] == 5


def test_signals_around_a_failed_task(extras, events):
    run(build_sqs_record("t.boom", "s2"))

    assert [name for name, _ in events] == ["task_prerun", "task_postrun", "task_failure"]
    postrun = events[1][1]
    failure = events[2][1]
    assert postrun["state"] == "FAILURE"
    assert failure["task_id"] == "s2"
    assert isinstance(failure["exception"], ValueError)  # the original, not a wrapper
    assert "ValueError: bad" in failure["traceback"]


def test_signals_around_a_retry(extras, events):
    run(build_sqs_record("t.retries", "s3"))

    assert [name for name, _ in events] == ["task_prerun", "task_retry", "task_postrun"]
    retry = events[1][1]
    assert isinstance(retry["reason"], ConnectionError)
    assert retry["eta"] is None
    assert events[2][1]["state"] == "RETRY"


@pytest.mark.parametrize("name,state", [("t.ignores", "IGNORED"), ("t.rejects", "REJECTED")])
def test_signals_for_ignore_and_reject(extras, events, name, state):
    run(build_sqs_record(name, "s4"))
    assert [n for n, _ in events] == ["task_prerun", "task_postrun"]
    assert events[1][1]["state"] == state


def test_an_unsupported_task_only_sends_the_failure_signal(extras, events):
    run(build_sqs_record("not.listed", "s5"))
    assert [name for name, _ in events] == ["task_failure"]


def test_a_receiver_that_raises_does_not_break_the_task(extras):
    def broken(**kwargs):
        raise RuntimeError("receiver bug")

    signals.task_success.connect(broken)
    try:
        result = run(build_sqs_record("t.add", "s6", args=[1, 1]))
    finally:
        signals.task_success.disconnect(broken)

    assert result["processed_tasks"][0]["status"] == "SUCCESS"
    assert TaskModel.get_task("s6")["result"]["result"] == 2


# -- metrics --------------------------------------------------------------------


@pytest.fixture
def metrics_on():
    from celery_cloud import metrics

    with patch.object(metrics.settings, "METRICS_ENABLED", True):
        yield


def emitted(capsys):
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")]
    return [(line["Task"], next(k for k in line if k.startswith("Task") and k not in ("Task", "TaskDuration")), "TaskDuration" in line) for line in lines]


def test_metrics_of_every_kind_of_outcome(extras, metrics_on, capsys):
    run(build_sqs_record("t.add", "m1", args=[1]))
    run(build_sqs_record("t.add", "m1", args=[1], message_id="dup"))
    run(build_sqs_record("t.boom", "m2"))
    run(build_sqs_record("t.retries", "m3"))
    run(build_sqs_record("t.ignores", "m4"))
    run(build_sqs_record("t.rejects", "m5"))
    run(build_sqs_record("t.add", "m6", headers={"eta": "2999-01-01T00:00:00+00:00"}))

    assert emitted(capsys) == [
        ("t.add", "TaskSucceeded", True),
        ("t.add", "TaskSkipped", False),  # a duplicate does not run: no duration
        ("t.boom", "TaskFailed", True),
        ("t.retries", "TaskRetried", True),
        ("t.ignores", "TaskIgnored", True),
        ("t.rejects", "TaskRejected", True),
        ("t.add", "TaskDelayed", False),
    ]


def test_a_message_that_cannot_be_decoded_is_counted_as_unknown(extras, metrics_on, capsys):
    record = build_sqs_record("t.add", "m7")
    record["body"] = "bm90IGpzb24="  # "not json"
    run(record)
    assert emitted(capsys) == [("unknown", "TaskFailed", False)]


def test_no_metrics_by_default(extras, capsys):
    run(build_sqs_record("t.add", "m8", args=[1]))
    assert capsys.readouterr().out == ""


def test_a_problem_writing_metrics_does_not_fail_the_task(extras, metrics_on):
    with patch("celery_cloud.runners.aws_lambda.metrics.emit", side_effect=OSError("disk")):
        result = run(build_sqs_record("t.add", "m9", args=[1]))
    assert result["processed_messages"] == 1


# -- init modules -----------------------------------------------------------------


@pytest.fixture
def fresh_init(monkeypatch):
    monkeypatch.setattr(aws_lambda, "_init_done", False)


def test_init_modules_are_imported_once(extras, fresh_init, monkeypatch):
    imported = []
    module = types.ModuleType("my_hooks")
    sys.modules["my_hooks"] = module
    monkeypatch.setattr(aws_lambda.settings, "INIT_MODULES", ["my_hooks"])
    real = aws_lambda.importlib.import_module
    monkeypatch.setattr(
        aws_lambda.importlib,
        "import_module",
        lambda name: imported.append(name) or real(name),
    )

    run(build_sqs_record("t.add", "i1", args=[1]))
    run(build_sqs_record("t.add", "i2", args=[1]))

    assert [name for name in imported if name == "my_hooks"] == ["my_hooks"]
    del sys.modules["my_hooks"]


def test_an_init_module_that_cannot_be_imported_does_not_stop_the_runner(
    extras, fresh_init, monkeypatch
):
    monkeypatch.setattr(aws_lambda.settings, "INIT_MODULES", ["does.not.exist"])
    result = run(build_sqs_record("t.add", "i3", args=[4]))
    assert result["processed_tasks"][0]["result"] == 4


# -- batch concurrency ----------------------------------------------------------------


def napping_batch():
    return [build_sqs_record("t.nap", f"n{i}", message_id=f"m{i}") for i in range(3)]


def test_records_run_one_after_the_other_by_default(extras):
    started = time.monotonic()
    result = run(*napping_batch())
    assert result["processed_messages"] == 3
    assert time.monotonic() - started >= 1.1
    assert len(set(seen_threads)) == 1


def test_records_run_at_the_same_time_with_batch_concurrency(extras, monkeypatch):
    monkeypatch.setattr(aws_lambda.settings, "BATCH_CONCURRENCY", 3)
    started = time.monotonic()
    result = run(*napping_batch())

    assert time.monotonic() - started < 1.0  # three 0.4 s tasks overlapped
    assert result["processed_messages"] == 3
    assert len(set(seen_threads)) == 3
    assert [t["task_id"] for t in result["processed_tasks"]] == ["n0", "n1", "n2"]


def test_concurrent_records_keep_their_own_outcome_and_trace(extras, monkeypatch):
    monkeypatch.setattr(aws_lambda.settings, "BATCH_CONCURRENCY", 4)
    result = run(
        build_sqs_record("t.add", "c1", args=[1], message_id="a"),
        build_sqs_record("t.boom", "c2", message_id="b"),
        build_sqs_record("t.add", "c3", args=[3], message_id="c"),
    )

    assert [t["task_id"] for t in result["processed_tasks"]] == ["c1", "c3"]
    assert result["failed_tasks"][0]["task_id"] == "c2"
    assert TaskModel.get_task("c3")["result"]["result"] == 3


def test_the_same_task_twice_in_a_concurrent_batch_runs_once(extras, monkeypatch):
    monkeypatch.setattr(aws_lambda.settings, "BATCH_CONCURRENCY", 2)
    result = run(
        build_sqs_record("t.nap", "same", message_id="a"),
        build_sqs_record("t.nap", "same", message_id="b"),
    )
    assert result["processed_messages"] == 1
    assert result["skipped_messages"] == 1


def test_a_single_record_does_not_need_threads(extras, monkeypatch):
    monkeypatch.setattr(aws_lambda.settings, "BATCH_CONCURRENCY", 8)
    result = run(build_sqs_record("t.add", "one", args=[1]))
    assert result["processed_messages"] == 1
