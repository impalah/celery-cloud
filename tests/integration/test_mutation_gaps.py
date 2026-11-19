"""Behaviours that mutation testing showed were not pinned down by other tests."""

import json
import sys
import time
import types
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from celery_cloud import Reject, signals, task
from celery_cloud.entities import Task
from celery_cloud.models.canvas_model import (
    ChordCounter,
    _chord_key,
    _group_key,
    group_children,
)
from celery_cloud.models.task_model import TaskModel, _task_key
from celery_cloud.runners import aws_lambda
from celery_cloud.runners.aws_lambda import lambda_handler
from sqs_helpers import build_sqs_record, record_from_sqs_message


@task(bind=True, max_retries=3, default_retry_delay=0)
def retrying(self):
    raise self.retry(exc=ConnectionError("down"))


@task(bind=True)
def rejecting(self):
    raise Reject("no", requeue=False)


@task(bind=True)
def reports(self):
    self.update_state(state="PROGRESS", meta={"n": 1})
    return "done"


def plain(args, kwargs):
    return sum(args)


@pytest.fixture
def gap(queue):
    module = types.ModuleType("gap_tasks")
    for function in (retrying, rejecting, reports, plain):
        setattr(module, function.__name__, function)
    sys.modules["gap_tasks"] = module
    routes = {f"t.{n}": f"task://gap_tasks/{n}" for n in ("retrying", "rejecting", "reports", "plain")}
    with patch.object(aws_lambda.settings, "TASKS", routes):
        yield queue
    del sys.modules["gap_tasks"]


def run(*records, context=None):
    return lambda_handler({"Records": list(records)}, context)


def raw(task_id):
    return json.loads(TaskModel.get(_task_key(task_id), consistent_read=True).result)


# -- extended meta reaches every state ---------------------------------------------------


@pytest.fixture
def extended(monkeypatch):
    monkeypatch.setattr(aws_lambda.settings, "RESULT_EXTENDED", True)
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "my-runner")


def check_meta(meta, name, retries=0):
    assert meta["name"] == name
    assert meta["worker"] == "my-runner"
    assert meta["queue"] == "my-queue"  # the last part of the ARN, not the whole ARN
    assert meta["retries"] == retries


def test_extended_meta_in_the_retry_state(gap, extended):
    run(build_sqs_record("t.retrying", "x1", args=[], headers={"retries": 2}))
    check_meta(raw("x1"), "t.retrying", retries=2)
    assert raw("x1")["status"] == "RETRY"


def test_extended_meta_in_the_rejected_state(gap, extended):
    run(build_sqs_record("t.rejecting", "x2"))
    check_meta(raw("x2"), "t.rejecting")
    assert raw("x2")["status"] == "REJECTED"


def test_extended_meta_with_a_custom_state(gap, extended):
    seen = {}

    @task(bind=True)
    def spy(self):
        self.update_state(state="PROGRESS", meta=1)
        seen.update(raw("x3"))

    sys.modules["gap_tasks"].spy = spy
    with patch.object(aws_lambda.settings, "TASKS", {"t.spy": "task://gap_tasks/spy"}):
        run(build_sqs_record("t.spy", "x3"))
    check_meta(seen, "t.spy")
    assert seen["status"] == "PROGRESS"


def test_extended_meta_when_the_task_is_not_supported(gap, extended):
    run(build_sqs_record("not.listed", "x4"))
    check_meta(raw("x4"), "not.listed")


def test_extended_meta_when_the_task_expired(gap, extended):
    past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    run(build_sqs_record("t.plain", "x5", headers={"expires": past}))
    check_meta(raw("x5"), "t.plain")
    assert raw("x5")["status"] == "REVOKED"


def test_extended_meta_when_a_retry_cannot_be_sent(gap, extended):
    with patch("celery_cloud.runners.aws_lambda.send", side_effect=RuntimeError("no queue")):
        run(build_sqs_record("t.retrying", "x6"))
    check_meta(raw("x6"), "t.retrying")
    assert raw("x6")["status"] == "FAILURE"


def test_extended_meta_survives_a_take_over(gap, extended):
    run(build_sqs_record("t.retrying", "x7"))
    (message,) = gap.receive()
    run(record_from_sqs_message(message))
    check_meta(raw("x7"), "t.retrying", retries=1)


# -- every signal carries the task id and name -------------------------------------------


def test_every_signal_carries_the_id_and_the_name(gap):
    log = []
    receivers = []
    for name in ("task_prerun", "task_postrun", "task_success", "task_failure", "task_retry"):
        def receiver(_n=name, **kwargs):
            log.append((_n, kwargs))
        receivers.append((getattr(signals, name), signals_connect(name, receiver)))

    try:
        run(build_sqs_record("t.plain", "g1", args=[1]))
        run(build_sqs_record("t.retrying", "g2"))
        run(build_sqs_record("t.rejecting", "g3"))
        run(build_sqs_record("not.listed", "g4"))
    finally:
        for signal, receiver in receivers:
            signal.disconnect(receiver)

    for name, kwargs in log:
        assert kwargs["task_id"] in {"g1", "g2", "g3", "g4"}, name
        assert kwargs["task"] in {"t.plain", "t.retrying", "t.rejecting", "not.listed"}, name
    retry = next(kw for name, kw in log if name == "task_retry")
    assert (retry["task_id"], retry["task"]) == ("g2", "t.retrying")
    assert isinstance(retry["eta"], datetime) is False  # the Retry had a countdown
    postruns = {kw["state"] for name, kw in log if name == "task_postrun"}
    assert postruns == {"SUCCESS", "RETRY", "REJECTED"}
    for name, kw in log:
        if name == "task_postrun" and kw["task_id"] == "g1":
            assert kw["args"] == [1] and kw["kwargs"] == {}


def signals_connect(name, receiver):
    return getattr(signals, name).connect(receiver)


# -- boundaries -----------------------------------------------------------------------------


def test_a_record_with_exactly_the_margin_left_is_not_started(gap):
    now = [100.0]
    stub = SimpleNamespace(monotonic=lambda: now[0], perf_counter=time.perf_counter)
    context = SimpleNamespace(get_remaining_time_in_millis=lambda: 10_000)  # == margin
    with patch.object(aws_lambda, "time", stub):
        result = run(build_sqs_record("t.plain", "b1", args=[1], message_id="mb"), context=context)
    assert result["batchItemFailures"] == [{"itemIdentifier": "mb"}]


def test_a_record_just_above_the_margin_is_started(gap):
    stub = SimpleNamespace(monotonic=lambda: 100.0, perf_counter=time.perf_counter)
    context = SimpleNamespace(get_remaining_time_in_millis=lambda: 10_001)
    with patch.object(aws_lambda, "time", stub):
        result = run(build_sqs_record("t.plain", "b2", args=[1]), context=context)
    assert result["processed_messages"] == 1


def test_an_eta_exactly_one_second_away_is_held(gap):
    with patch.object(Task, "eta_seconds", return_value=1.0):
        result = run(build_sqs_record("t.plain", "b3", args=[1], headers={"eta": "2999-01-01"}))
    assert result["delayed_messages"] == 1
    assert result["delayed_tasks"][0]["delay_seconds"] == 1


def test_an_eta_just_below_a_second_runs_now(gap):
    with patch.object(Task, "eta_seconds", return_value=0.99):
        result = run(build_sqs_record("t.plain", "b4", args=[1], headers={"eta": "2999-01-01"}))
    assert result["processed_messages"] == 1


def test_two_records_and_two_workers_do_use_threads(gap, monkeypatch):
    monkeypatch.setattr(aws_lambda.settings, "BATCH_CONCURRENCY", 2)
    threads = set()

    def spy(record, deadline):
        import threading

        threads.add(threading.get_ident())
        return aws_lambda._Outcome(aws_lambda.SkippedTask(message_id="m", task_id="t", reason="r"))

    with patch.object(aws_lambda, "_process_record", spy):
        run(build_sqs_record("t.plain", "p1"), build_sqs_record("t.plain", "p2"))
    assert threads and threading_main() not in threads


def threading_main():
    import threading

    return threading.main_thread().ident


def test_the_response_has_no_delayed_entries_when_nothing_was_delayed(gap):
    result = run(build_sqs_record("t.plain", "r1", args=[1]))
    assert result["delayed_messages"] is None
    assert result["delayed_tasks"] is None


def test_a_batch_that_stops_early_is_not_cut_short(gap):
    """A skipped record in the middle must not drop the ones after it."""
    run(build_sqs_record("t.plain", "dup", args=[1]))
    result = run(
        build_sqs_record("t.plain", "dup", args=[1], message_id="m1"),
        build_sqs_record("t.plain", "after", args=[2], message_id="m2"),
    )
    assert result["skipped_messages"] == 1
    assert result["processed_tasks"][0]["task_id"] == "after"


def test_a_retry_message_is_a_task_with_its_own_retries_in_extended_meta(gap, extended):
    run(build_sqs_record("t.plain", "e1", args=[1], headers={"retries": 3}))
    assert raw("e1")["retries"] == 3


# -- backend details ----------------------------------------------------------------------------


def started(task_id, **attributes):
    TaskModel(
        id=_task_key(task_id),
        result=json.dumps({"status": "STARTED", "task_id": task_id}).encode(),
        **attributes,
    ).save()


def test_a_take_over_rewrites_the_item_completely(aws):
    started("k1", attempt=1)
    TaskModel.insert_task("k1", retries=2)

    item = TaskModel.get(_task_key("k1"), consistent_read=True)
    meta = json.loads(item.result)
    assert item.attempt == 2
    assert meta["status"] == "STARTED"
    assert meta["children"] == []
    assert meta["task_id"] == "k1"
    assert datetime.fromisoformat(meta["date_done"]).tzinfo is not None
    assert item.timestamp > time.time() - 5
    assert item.ttl > time.time()


def test_the_take_over_reads_the_item_with_a_consistent_read(aws):
    started("k2", attempt=1)
    real_get = TaskModel.get
    seen = []

    def spy(*args, **kwargs):
        seen.append(kwargs.get("consistent_read"))
        return real_get(*args, **kwargs)

    with patch.object(TaskModel, "get", side_effect=spy):
        TaskModel.insert_task("k2", retries=2)
        TaskModel.is_revoked("k2")
        group_children("none")

    assert seen == [True, True, True]


def test_store_result_writes_a_complete_item(aws):
    TaskModel.store_result("k3", "FAILURE", {"exc_type": "X"}, traceback="tb")

    item = TaskModel.get(_task_key("k3"), consistent_read=True)
    meta = json.loads(item.result)
    assert meta["status"] == "FAILURE"
    assert meta["result"] == {"exc_type": "X"}
    assert meta["traceback"] == "tb"
    assert meta["children"] == []
    assert datetime.fromisoformat(meta["date_done"]).tzinfo is not None
    assert item.ttl > time.time()


def test_store_result_failure_keeps_the_original_text_as_detail():
    from celery_cloud.exceptions import BackendException

    with patch.object(TaskModel, "save", side_effect=RuntimeError("full")):
        with pytest.raises(BackendException) as raised:
            TaskModel.store_result("k4", "FAILURE")
    assert raised.value.detail == "full"


def test_the_counter_item_is_deleted_when_the_chord_is_done(gap):
    group = [["g", None], [[["h0", None], None]]]
    TaskModel(id=_group_key("g"), result=json.dumps({"result": group}).encode()).save()
    ChordCounter(id=_chord_key("g"), chord_count=0).save()
    body = {"task": "t.plain", "args": [], "kwargs": {}, "options": {"task_id": "body"}}

    run(build_sqs_record("t.plain", "h0", args=[1], headers={"group": "g"}, embed={"chord": body}))

    with pytest.raises(ChordCounter.DoesNotExist):
        ChordCounter.get(_chord_key("g"), consistent_read=True)
    with pytest.raises(TaskModel.DoesNotExist):
        TaskModel.get(_group_key("g"), consistent_read=True)


def test_a_revoked_header_task_fails_the_chord(gap):
    group = [["g", None], [[["h0", None], None]]]
    TaskModel(id=_group_key("g"), result=json.dumps({"result": group}).encode()).save()
    ChordCounter(id=_chord_key("g"), chord_count=0).save()
    TaskModel.store_result("h0", "REVOKED", {"exc_type": "TaskRevokedError", "exc_message": ["x"]})
    body = {"task": "t.plain", "args": [], "kwargs": {}, "options": {"task_id": "body"}}

    run(build_sqs_record("t.plain", "other", args=[1], headers={"group": "g"}, embed={"chord": body}))

    assert raw("body")["status"] == "FAILURE"
    assert "Dependency h0 raised TaskRevokedError('x')" in raw("body")["result"]["exc_message"][0]


@pytest.mark.parametrize(
    "headers,embed",
    [
        ({"group": "g"}, {}),  # in a group but no chord
        ({}, {"chord": {"task": "body", "options": {}}}),  # a chord but no group
    ],
)
def test_chord_accounting_needs_both_the_group_and_the_chord(gap, headers, embed):
    group = [["g", None], [[["h0", None], None]]]
    TaskModel(id=_group_key("g"), result=json.dumps({"result": group}).encode()).save()
    ChordCounter(id=_chord_key("g"), chord_count=0).save()

    run(build_sqs_record("t.plain", "h0", args=[1], headers=headers, embed=embed))

    assert ChordCounter.get(_chord_key("g"), consistent_read=True).chord_count == 0
    assert gap.receive() == []


def test_the_chord_body_goes_to_the_queue_of_the_header_task(gap):
    gap.client.create_queue(QueueName="elsewhere")
    group = [["g", None], [[["h0", None], None]]]
    TaskModel(id=_group_key("g"), result=json.dumps({"result": group}).encode()).save()
    ChordCounter(id=_chord_key("g"), chord_count=0).save()
    body = {"task": "t.plain", "args": [], "kwargs": {}, "options": {"task_id": "body"}}
    run(build_sqs_record("t.plain", "h0", args=[1], headers={"group": "g"}, embed={"chord": body}))
    (message,) = gap.receive()
    envelope = json.loads(__import__("base64").b64decode(message["Body"]))
    assert envelope["properties"]["delivery_info"]["routing_key"] == "my-queue"
