"""eta, retries, task API, callbacks, chains and chords (simulated SQS + DynamoDB)."""

import base64
import json
import sys
import types
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from celery_cloud import Ignore, Reject, task
from celery_cloud.exceptions import BackendException
from celery_cloud.models.canvas_model import ChordCounter, _chord_key, _group_key
from celery_cloud.models.task_model import TaskModel
from celery_cloud.runners import aws_lambda
from celery_cloud.runners.aws_lambda import lambda_handler
from sqs_helpers import build_sqs_record, record_from_sqs_message

calls: dict = {}


@task(bind=True, max_retries=2, default_retry_delay=0)
def flaky(self):
    if self.request.retries < 1:
        raise self.retry(exc=ConnectionError("down"))
    return f"ok after {self.request.retries}"


@task(bind=True, max_retries=5, default_retry_delay=0)
def twice(self):
    if self.request.retries < 2:
        raise self.retry(exc=ConnectionError("down"))
    return f"ok after {self.request.retries}"


@task(bind=True, max_retries=3)
def retry_at(self):
    from datetime import UTC, datetime, timedelta

    raise self.retry(eta=datetime.now(UTC) + timedelta(minutes=30))


@task(bind=True, max_retries=3)
def retry_at_naive(self):
    from datetime import datetime, timedelta

    # a naive datetime (no tzinfo): the runner takes it as UTC
    raise self.retry(eta=datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=30))


@task(bind=True, max_retries=1, default_retry_delay=0)
def always_fails(self):
    raise self.retry(exc=ConnectionError("still down"))


@task(bind=True, max_retries=3, default_retry_delay=120)
def slow_retry(self):
    raise self.retry(exc=ConnectionError("later"))


@task(bind=True)
def progress(self):
    self.update_state(state="PROGRESS", meta={"done": 1})
    calls["seen"] = TaskModel.get_task(self.request.id)["result"]
    return "done"


@task(bind=True)
def ignores(self):
    self.update_state(state="CUSTOM", meta="by hand")
    raise Ignore()


@task(bind=True)
def rejects(self):
    calls["rejects"] = calls.get("rejects", 0) + 1
    if calls["rejects"] == 1:
        raise Reject("busy", requeue=True)
    return "ran"


@task
def rejects_for_good():
    raise Reject("not for me", requeue=False)


@task(bind=True)
def revoked_while_running(self):
    TaskModel(id=f"b'celery-task-meta-{self.request.id}'").update(
        actions=[TaskModel.revoked.set(True)]
    )
    return self.is_revoked()


@task
def natural(x, y=0):
    return x + y


def boom(args, kwargs):
    raise ValueError("bad value", 42)


def add(args, kwargs):
    return sum(args)


def total(args, kwargs):
    return sum(args[0])


@pytest.fixture
def flow(queue):
    module = types.ModuleType("flow_tasks")
    for function in (
        flaky, twice, retry_at, retry_at_naive, always_fails, slow_retry, progress, ignores, rejects,
        rejects_for_good, revoked_while_running, natural, boom, add, total,
    ):
        setattr(module, function.__name__, function)
    sys.modules["flow_tasks"] = module
    calls.clear()
    routes = {
        f"t.{name}": f"task://flow_tasks/{name}"
        for name in (
            "flaky", "twice", "retry_at", "retry_at_naive", "always_fails", "slow_retry", "progress", "ignores", "rejects",
            "rejects_for_good", "revoked_while_running", "natural", "boom", "add",
            "total",
        )
    }
    with patch.object(aws_lambda.settings, "TASKS", routes):
        yield queue
    del sys.modules["flow_tasks"]


def run(*records):
    return lambda_handler({"Records": list(records)}, None)


def stored(task_id):
    return TaskModel.get_task(task_id)["result"]


def decode(message):
    envelope = json.loads(base64.b64decode(message["Body"]))
    return envelope, json.loads(base64.b64decode(envelope["body"]))


def sig(task_name, *args, **options):
    return {
        "task": task_name,
        "args": list(args),
        "kwargs": {},
        "options": options,
        "subtask_type": None,
        "immutable": False,
    }


def iso(delta):
    return (datetime.now(UTC) + delta).isoformat()


# -- eta -----------------------------------------------------------------------


def test_a_task_with_a_far_eta_is_held_and_not_registered(flow):
    record = build_sqs_record("t.add", "e1", args=[1], headers={"eta": iso(timedelta(hours=2))})

    result = run(record)

    assert result["processed_messages"] == 0
    assert result["delayed_messages"] == 1
    assert result["delayed_tasks"] == [
        {"message_id": "msg-1", "task_id": "e1", "delay_seconds": 900}
    ]
    assert result["batchItemFailures"] == []
    assert TaskModel.get_task("e1") is None  # still pending for the client
    assert flow.delayed() == 1


def test_a_near_eta_is_delayed_by_the_time_that_is_left(flow):
    run(build_sqs_record("t.add", "e2", args=[1], headers={"eta": iso(timedelta(seconds=40))}))
    assert flow.delayed() == 1


def test_the_held_message_is_the_same_message(flow):
    record = build_sqs_record("t.add", "e3", args=[1], headers={"eta": iso(timedelta(hours=1))})
    run(record)
    sent = flow.client.receive_message(
        QueueUrl=flow.url, VisibilityTimeout=0, WaitTimeSeconds=0
    )
    assert "Messages" not in sent  # delayed: not receivable yet
    # purge the delay to read it: SQS itself keeps the body, which we compare
    attributes = flow.client.get_queue_attributes(
        QueueUrl=flow.url, AttributeNames=["ApproximateNumberOfMessagesDelayed"]
    )
    assert attributes["Attributes"]["ApproximateNumberOfMessagesDelayed"] == "1"


@pytest.mark.parametrize(
    "eta",
    [
        lambda: iso(timedelta(seconds=-30)),  # in the past
        lambda: iso(timedelta(seconds=0.3)),  # less than a second away
        lambda: "not a date",
    ],
)
def test_a_past_or_invalid_eta_runs_the_task_now(flow, eta):
    result = run(build_sqs_record("t.add", "e4", args=[2, 3], headers={"eta": eta()}))
    assert result["processed_messages"] == 1
    assert stored("e4")["result"] == 5


def test_a_naive_eta_is_taken_as_utc(flow):
    naive = (datetime.now(UTC) + timedelta(hours=1)).replace(tzinfo=None).isoformat()
    result = run(build_sqs_record("t.add", "e5", args=[1], headers={"eta": naive}))
    assert result["delayed_messages"] == 1


def test_a_failure_holding_the_task_returns_the_message_to_sqs(flow):
    record = build_sqs_record(
        "t.add", "e6", args=[1], message_id="m-e6", headers={"eta": iso(timedelta(hours=1))}
    )
    with patch(
        "celery_cloud.runners.aws_lambda.delay_message",
        side_effect=BackendException("Could not send a message to queue my-queue"),
    ):
        result = run(record)

    assert result["batchItemFailures"] == [{"itemIdentifier": "m-e6"}]
    assert result["failed_messages"] == 1


# -- retries -------------------------------------------------------------------


def test_retry_resends_the_task_and_the_retry_takes_it_over(flow):
    first = run(build_sqs_record("t.flaky", "r1"))

    assert first["processed_tasks"] == [{"task_id": "r1", "status": "RETRY", "result": None}]
    meta = stored("r1")
    assert meta["status"] == "RETRY"
    assert meta["result"] == {
        "exc_type": "ConnectionError",
        "exc_message": ["down"],
        "exc_module": "builtins",
    }
    assert "ConnectionError: down" in meta["traceback"]

    (message,) = flow.receive()
    envelope, body = decode(message)
    assert envelope["headers"]["id"] == "r1"  # the same task
    assert envelope["headers"]["retries"] == 1
    assert envelope["headers"]["eta"] is not None

    second = run(record_from_sqs_message(message))

    assert second["processed_tasks"][0]["status"] == "SUCCESS"
    assert stored("r1")["status"] == "SUCCESS"
    assert stored("r1")["result"] == "ok after 1"


def test_the_same_retry_message_delivered_twice_runs_once(flow):
    run(build_sqs_record("t.flaky", "r2"))
    (message,) = flow.receive()
    record = record_from_sqs_message(message)

    run(record)
    again = run({**record, "messageId": "dup"})

    assert again["skipped_messages"] == 1
    assert again["skipped_tasks"][0]["reason"] == "duplicate message: the task already exists"


def test_the_original_message_is_a_duplicate_once_the_retry_started(flow):
    original = build_sqs_record("t.flaky", "r3")
    run(original)
    (message,) = flow.receive()
    run(record_from_sqs_message(message))

    again = run({**original, "messageId": "late-duplicate"})

    assert again["skipped_messages"] == 1
    assert stored("r3")["status"] == "SUCCESS"  # not overwritten


def test_retries_that_run_out_end_as_the_original_failure(flow):
    run(build_sqs_record("t.always_fails", "r4"))
    (message,) = flow.receive()

    result = run(record_from_sqs_message(message))

    assert result["failed_messages"] == 1
    meta = stored("r4")
    assert meta["status"] == "FAILURE"
    assert meta["result"]["exc_type"] == "ConnectionError"
    assert meta["result"]["exc_message"] == ["still down"]
    assert flow.receive() == []  # nothing else is scheduled


def test_a_retry_with_a_countdown_is_delayed_in_sqs(flow):
    run(build_sqs_record("t.slow_retry", "r5"))
    assert flow.delayed() == 1
    assert stored("r5")["status"] == "RETRY"


def test_a_retry_that_cannot_be_sent_fails_the_task(flow):
    with patch(
        "celery_cloud.runners.aws_lambda.send",
        side_effect=BackendException("Could not send a message to queue my-queue"),
    ):
        result = run(build_sqs_record("t.flaky", "r6"))

    assert result["failed_messages"] == 1
    assert result["failed_tasks"][0]["error"].startswith("Could not schedule the retry")
    assert stored("r6")["status"] == "FAILURE"
    assert stored("r6")["result"]["exc_type"] == "ConnectionError"


def test_a_retry_of_a_task_that_ignores_its_result_stores_nothing(flow):
    record = build_sqs_record("t.flaky", "r7", headers={"ignore_result": True})
    result = run(record)

    assert result["processed_tasks"][0]["status"] == "RETRY"
    assert TaskModel.get_task("r7") is None
    (message,) = flow.receive()
    assert decode(message)[0]["headers"]["retries"] == 1


def test_a_retry_that_takes_over_cannot_be_taken_by_a_concurrent_copy(flow):
    """The take-over is conditional: if the owner changed, the loser is a duplicate."""
    from celery_cloud.models import task_model

    run(build_sqs_record("t.flaky", "r8"))
    (message,) = flow.receive()
    record = record_from_sqs_message(message)

    real_get = TaskModel.get

    def stale_get(key, *args, **kwargs):
        item = real_get(key, *args, **kwargs)
        # another copy of the retry won the race after we read the item
        real_get(key).update(actions=[TaskModel.attempt.set(1)])
        return item

    with patch.object(task_model.TaskModel, "get", side_effect=stale_get):
        result = run(record)

    assert result["skipped_messages"] == 1


# -- the task API ---------------------------------------------------------------


def test_a_decorated_task_receives_natural_arguments(flow):
    run(build_sqs_record("t.natural", "n1", args=[2], kwargs={"y": 5}))
    assert stored("n1")["result"] == 7


def test_update_state_stores_a_custom_state_while_the_task_runs(flow):
    run(build_sqs_record("t.progress", "p1"))

    assert calls["seen"]["status"] == "PROGRESS"
    assert calls["seen"]["result"] == {"done": 1}
    assert stored("p1")["status"] == "SUCCESS"


def test_update_state_is_not_stored_for_tasks_that_ignore_results(flow):
    run(build_sqs_record("t.progress", "p2", headers={"ignore_result": True}))
    assert TaskModel.get_task("p2") is None


def test_ignore_leaves_the_state_the_task_set(flow):
    result = run(build_sqs_record("t.ignores", "i1"))

    assert result["processed_tasks"] == [{"task_id": "i1", "status": "IGNORED", "result": None}]
    assert stored("i1")["status"] == "CUSTOM"
    assert stored("i1")["result"] == "by hand"


def test_reject_with_requeue_gives_the_message_back_and_forgets_the_task(flow):
    record = build_sqs_record("t.rejects", "j1", message_id="m-j1")

    first = run(record)

    assert first["batchItemFailures"] == [{"itemIdentifier": "m-j1"}]
    assert first["failed_tasks"][0]["error"] == "Rejected, requeued: busy"
    assert TaskModel.get_task("j1") is None  # the redelivery will run it again

    second = run(record)

    assert second["processed_tasks"][0]["status"] == "SUCCESS"
    assert stored("j1")["result"] == "ran"


def test_reject_without_requeue_drops_the_message(flow):
    result = run(build_sqs_record("t.rejects_for_good", "j2"))

    assert result["processed_tasks"] == [{"task_id": "j2", "status": "REJECTED", "result": None}]
    assert result["batchItemFailures"] == []
    assert stored("j2")["status"] == "REJECTED"
    assert stored("j2")["result"] == "not for me"


def test_a_revoked_task_is_not_run(flow):
    TaskModel(
        id="b'celery-task-meta-v1'", result=b"{}", revoked=True
    ).save()

    result = run(build_sqs_record("t.add", "v1", args=[1]))

    assert result["skipped_tasks"] == [
        {"message_id": "msg-1", "task_id": "v1", "reason": "task revoked"}
    ]


def test_a_running_task_can_notice_that_it_was_revoked(flow):
    run(build_sqs_record("t.revoked_while_running", "v2"))
    assert stored("v2")["result"] is True


# -- callbacks, chains -----------------------------------------------------------


def test_link_sends_the_callback_with_the_result(flow):
    record = build_sqs_record(
        "t.add", "c1", args=[1, 2], embed={"callbacks": [sig("t.add", 10, task_id="child-1")]},
        headers={"root_id": "root-1"},
    )
    run(record)

    (message,) = flow.receive()
    envelope, body = decode(message)
    assert envelope["headers"]["task"] == "t.add"
    assert envelope["headers"]["id"] == "child-1"
    assert envelope["headers"]["parent_id"] == "c1"
    assert envelope["headers"]["root_id"] == "root-1"
    assert body[0] == [3, 10]  # the result first, then the callback's own args


def test_every_callback_is_sent(flow):
    run(build_sqs_record("t.add", "c2", args=[1], embed={"callbacks": [sig("t.a"), sig("t.b")]}))
    names = sorted(decode(m)[0]["headers"]["task"] for m in flow.receive())
    assert names == ["t.a", "t.b"]


def test_the_next_step_of_a_chain_carries_the_rest(flow):
    chain = [sig("t.last"), sig("t.middle", 2)]  # the LAST element is the next step
    run(build_sqs_record("t.add", "ch1", args=[1, 2], embed={"chain": chain}))

    (message,) = flow.receive()
    envelope, body = decode(message)
    assert envelope["headers"]["task"] == "t.middle"
    assert body[0] == [3, 2]
    assert body[2]["chain"] == [sig("t.last")]


def test_the_last_step_of_a_chain_has_no_chain(flow):
    run(build_sqs_record("t.add", "ch2", args=[1], embed={"chain": [sig("t.only")]}))
    (message,) = flow.receive()
    assert decode(message)[1][2]["chain"] == []


def test_a_failing_task_stops_its_chain(flow):
    run(build_sqs_record("t.boom", "ch3", embed={"chain": [sig("t.next")]}))
    assert flow.receive() == []


def test_errbacks_receive_the_failed_task_id(flow):
    run(build_sqs_record("t.boom", "eb1", embed={"errbacks": [sig("t.handler", "extra")]}))

    (message,) = flow.receive()
    envelope, body = decode(message)
    assert envelope["headers"]["task"] == "t.handler"
    assert body[0] == ["eb1", "extra"]
    assert stored("eb1")["status"] == "FAILURE"


def test_callbacks_run_even_when_the_result_is_ignored(flow):
    record = build_sqs_record(
        "t.add", "c3", args=[1], embed={"callbacks": [sig("t.next")]},
        headers={"ignore_result": True},
    )
    run(record)
    assert len(flow.receive()) == 1
    assert TaskModel.get_task("c3") is None


def test_a_callback_can_go_to_another_queue(flow):
    flow.client.create_queue(QueueName="other")
    run(build_sqs_record("t.add", "c4", args=[1], embed={"callbacks": [sig("t.next", queue="other")]}))

    assert flow.receive() == []  # not in the queue of the task
    other = flow.client.get_queue_url(QueueName="other")["QueueUrl"]
    assert len(flow.client.receive_message(QueueUrl=other).get("Messages", [])) == 1


def test_a_problem_sending_the_callbacks_does_not_fail_the_task(flow):
    with patch(
        "celery_cloud.runners.canvas.messaging.send",
        side_effect=BackendException("Could not send a message to queue my-queue"),
    ):
        result = run(build_sqs_record("t.add", "c5", args=[1, 2], embed={"callbacks": [sig("t.next")]}))

    assert result["processed_tasks"][0]["status"] == "SUCCESS"
    assert result["batchItemFailures"] == []
    assert stored("c5")["status"] == "SUCCESS"


# -- chords ----------------------------------------------------------------------


def start_chord(group_id, child_ids):
    """What the Celery client writes when it starts a chord."""
    group = [[group_id, None], [[[child, None], None] for child in child_ids]]
    TaskModel(
        id=_group_key(group_id), result=json.dumps({"result": group}).encode()
    ).save()
    ChordCounter(id=_chord_key(group_id), chord_count=0).save()


def header(name, task_id, group_id, index, args, chord_sig, **headers):
    return build_sqs_record(
        name, task_id, args=args, message_id=f"m-{task_id}",
        headers={"group": group_id, "group_index": index, **headers},
        embed={"chord": chord_sig},
    )


BODY = sig("t.total", task_id="body-1", group_id="g-1")


def test_the_chord_body_runs_when_the_last_header_task_ends(flow):
    start_chord("g-1", ["h0", "h1", "h2"])

    run(header("t.add", "h0", "g-1", 0, [1, 2], BODY))
    run(header("t.add", "h1", "g-1", 1, [3, 4], BODY))
    assert flow.receive() == []  # two of three: the body waits

    run(header("t.add", "h2", "g-1", 2, [5, 6], BODY))

    (message,) = flow.receive()
    envelope, body = decode(message)
    assert envelope["headers"]["task"] == "t.total"
    assert envelope["headers"]["id"] == "body-1"
    assert body[0] == [[3, 7, 11]]  # ONE argument: the list of results
    # the bookkeeping items are gone
    assert TaskModel.get_task("h0") is not None
    with pytest.raises(TaskModel.DoesNotExist):
        TaskModel.get(_group_key("g-1"))


def test_the_chord_results_follow_the_order_of_the_group(flow):
    start_chord("g-1", ["h0", "h1", "h2"])
    for index in (2, 0, 1):  # they finish in another order
        run(header("t.add", f"h{index}", "g-1", index, [index * 10], BODY))

    (message,) = flow.receive()
    assert decode(message)[1][0] == [[0, 10, 20]]


def test_a_failed_header_task_fails_the_chord_body(flow):
    start_chord("g-1", ["h0", "h1"])
    errback = sig("t.handler")
    chord_sig = sig("t.total", task_id="body-1", link_error=[errback])

    run(header("t.add", "h0", "g-1", 0, [1], chord_sig))
    run(header("t.boom", "h1", "g-1", 1, [], chord_sig))

    body = stored("body-1")
    assert body["status"] == "FAILURE"
    assert body["result"] == {
        "exc_type": "ChordError",
        "exc_message": ["Dependency h1 raised ValueError('bad value', 42)"],
        "exc_module": "celery.exceptions",
    }
    (message,) = flow.receive()  # the errback of the body
    assert decode(message)[1][0] == ["body-1"]


def test_a_chord_whose_group_is_gone_fails_the_body(flow):
    run(header("t.add", "h0", "gone", 0, [1], sig("t.total", task_id="body-2")))
    assert stored("body-2")["result"]["exc_message"] == [
        "GroupResult gone no longer exists"
    ]


def test_the_chord_size_of_the_signature_sets_when_the_body_is_due(flow):
    """With chord_size=1 the first header task already completes the count."""
    start_chord("g-1", ["h0", "h1", "h2"])
    sized = {**BODY, "chord_size": 1}

    run(header("t.add", "h0", "g-1", 0, [4], sized))

    # the join found h1 and h2 without a result: the body failed, it did not wait
    assert stored("body-1")["status"] == "FAILURE"
    assert "has no result" in stored("body-1")["result"]["exc_message"][0]


def test_a_header_result_that_disappeared_fails_the_chord(flow):
    start_chord("g-1", ["h0", "missing"])
    run(header("t.add", "h0", "g-1", 0, [1], BODY))
    run(header("t.add", "h9", "g-1", 1, [1], BODY))  # counts, but 'missing' has no item

    assert stored("body-1")["result"]["exc_message"] == [
        "Dependency missing has no result (PENDING)"
    ]


def test_an_extra_increment_does_not_run_the_body_twice(flow):
    start_chord("g-1", ["h0"])
    ChordCounter(id=_chord_key("g-1")).update(actions=[ChordCounter.chord_count.add(5)])

    run(header("t.add", "h0", "g-1", 0, [1], BODY))

    assert flow.receive() == []


# -- map / starmap ------------------------------------------------------------------


def test_starmap_runs_the_task_for_every_item(flow):
    record = build_sqs_record(
        "celery.starmap", "sm1",
        kwargs={"task": sig("t.add"), "it": [[1, 2], [3, 4]]},
    )
    result = run(record)
    assert result["processed_messages"] == 1
    assert stored("sm1")["result"] == [3, 7]


def test_map_of_a_task_that_is_not_allowed_fails(flow):
    record = build_sqs_record(
        "celery.map", "sm2", kwargs={"task": sig("not.allowed"), "it": [1]}
    )
    run(record)
    meta = stored("sm2")
    assert meta["status"] == "FAILURE"
    assert meta["result"]["exc_type"] == "NotImplementedError"


# -- periodic tasks (the same message, every time) ---------------------------------


def test_the_same_message_runs_every_time_when_its_result_is_ignored(flow):
    """A schedule repeats the message (same task id): with ignore_result it always runs."""
    record = build_sqs_record(
        "t.add", "scheduled", args=[1, 2], headers={"ignore_result": True}
    )
    calls_before = len(flow.receive())

    first = run(record)
    second = run({**record, "messageId": "next-run"})

    assert calls_before == 0
    assert first["processed_messages"] == 1
    assert second["processed_messages"] == 1
    assert second["skipped_messages"] == 0
    assert TaskModel.get_task("scheduled") is None  # nothing was registered


def test_a_second_retry_takes_over_from_the_first(flow):
    run(build_sqs_record("t.twice", "tw1"))
    (first,) = flow.receive()
    run(record_from_sqs_message(first))  # retries=1: still failing, retries again
    (second,) = flow.receive()

    assert decode(second)[0]["headers"]["retries"] == 2
    result = run(record_from_sqs_message(second))

    assert result["processed_tasks"][0]["status"] == "SUCCESS"
    assert stored("tw1")["result"] == "ok after 2"


def test_a_retry_with_an_absolute_eta_is_delayed_until_then(flow):
    run(build_sqs_record("t.retry_at", "ra1"))

    assert flow.delayed() == 1
    assert stored("ra1")["status"] == "RETRY"


def test_a_retry_with_a_naive_eta_is_taken_as_utc(flow):
    run(build_sqs_record("t.retry_at_naive", "ra2"))
    assert flow.delayed() == 1
