"""The server examples of the documentation (pages_source/examples) really work.

The documentation embeds those files with ``literalinclude``; running them through
the handler keeps the published examples honest.
"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from moto import mock_aws

from celery_cloud.models.task_model import TaskModel
from celery_cloud.runners import aws_lambda
from celery_cloud.runners.aws_lambda import lambda_handler

from sqs_helpers import build_sqs_record

EXAMPLES = Path(__file__).resolve().parents[2] / "pages_source" / "examples"
REGION = "eu-west-1"

TASKS = {
    "calculator.add": "task://calculator/add",
    "calculator.subtract": "task://calculator/subtract",
    "calculator.divide": "task://calculator/divide",
    "reports.summarize": "task://reports/summarize",
    "calculator.total": "task://calculator/total",
    "calculator.report_error": "task://calculator/report_error",
    "jobs.fetch": "task://jobs/fetch",
    "jobs.sync_account": "task://jobs/sync_account",
    "jobs.import_rows": "task://jobs/import_rows",
    "jobs.export_report": "task://jobs/export_report",
    "jobs.long_job": "task://jobs/long_job",
}


@pytest.fixture(autouse=True)
def aws(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)
    monkeypatch.syspath_prepend(str(EXAMPLES / "server"))
    monkeypatch.syspath_prepend(str(EXAMPLES / "remote"))
    with mock_aws():
        TaskModel.Meta.region = REGION
        TaskModel.create_table(billing_mode="PAY_PER_REQUEST", wait=True)
        with patch.object(aws_lambda.settings, "TASKS", TASKS):
            yield
    for name in ("calculator", "reports", "handler", "jobs", "signals_setup"):
        sys.modules.pop(name, None)


def run(task: str, task_id: str, args=None, kwargs=None, timelimit=None):
    record = build_sqs_record(
        task, task_id, args=args, kwargs=kwargs, timelimit=timelimit
    )
    return lambda_handler({"Records": [record]}, None)


def stored(task_id: str) -> dict:
    return TaskModel.get_task(task_id)["result"]


def test_add_uses_args_and_kwargs():
    run("calculator.add", "a1", args=[10, 3], kwargs={"extra": 5})
    assert stored("a1")["status"] == "SUCCESS"
    assert stored("a1")["result"] == 18


def test_subtract_with_one_value_is_a_failure():
    out = run("calculator.subtract", "s1", args=[5])
    assert out["failed_messages"] == 1
    meta = stored("s1")
    assert meta["status"] == "FAILURE"
    assert "subtract needs at least 2 values" in meta["result"]["exc_message"][0]


def test_divide_by_zero_is_a_failure():
    run("calculator.divide", "d0", args=[1, 0])
    assert stored("d0")["status"] == "FAILURE"
    assert "division by zero" in stored("d0")["result"]["exc_message"][0]


def test_divide():
    run("calculator.divide", "d1", args=[10, 4])
    assert stored("d1")["result"] == 2.5


def test_structured_task_round_trip():
    request = {"id": "r-1", "text": "Serverless workers scale to zero when idle"}
    run("reports.summarize", "r1", args=[request])
    assert stored("r1")["result"] == {
        "id": "r-1",
        "words": 7,
        "first_words": "Serverless workers scale to zero",
    }


def test_remote_handler_response_shape():
    from handler import lambda_handler as remote  # pages_source/examples/remote

    response = remote({"args": [22, 31], "kwargs": {}}, None)
    assert response["body"] == 53


def test_total_is_the_chord_body():
    run("calculator.total", "tt1", args=[[3, 7, 11]])
    assert stored("tt1")["result"] == 21


def test_the_error_callback_receives_the_failed_task_id():
    run("calculator.report_error", "er1", args=["some-task-id"])
    assert stored("er1")["result"] == "handled failure of some-task-id"


def test_fetch_retries_until_the_page_works(monkeypatch):
    """A flaky URL fails twice; the third attempt (retries=2) succeeds."""
    from celery_cloud.runners import aws_lambda

    sent = []
    monkeypatch.setattr(aws_lambda, "send", lambda queue, body, delay_seconds=0: sent.append(body))

    run("jobs.fetch", "f1", args=["https://flaky.example/x"])
    assert stored("f1")["status"] == "RETRY"
    assert len(sent) == 1

    record = build_sqs_record(
        "jobs.fetch", "f1", args=["https://flaky.example/x"], headers={"retries": 2}
    )
    lambda_handler({"Records": [record]}, None)
    assert stored("f1")["result"] == {
        "url": "https://flaky.example/x",
        "attempts": 3,
        "bytes": 2300,
    }


def test_fetch_of_a_normal_url_needs_no_retry():
    run("jobs.fetch", "f2", args=["https://example.com"])
    assert stored("f2")["result"]["attempts"] == 1


def test_import_rows_reports_progress():
    run("jobs.import_rows", "ir1", args=[3])
    assert stored("ir1")["result"] == {"imported": 3}


def test_export_report_returns_a_partial_report_when_the_soft_limit_hits():
    run("jobs.export_report", "ex1", args=[10], timelimit=[None, 0.3])
    assert stored("ex1")["result"] == "partial report (stopped by the soft time limit)"


def test_export_report_completes_when_there_is_time():
    run("jobs.export_report", "ex2", args=[0.01])
    assert stored("ex2")["result"] == "complete report"


def test_the_signal_receivers_connect_when_the_module_is_imported():
    from celery_cloud import signals

    before = len(signals.task_prerun._receivers)
    import signals_setup  # noqa: F401

    assert len(signals.task_prerun._receivers) == before + 1
    run("calculator.add", "sg1", args=[1, 1])
    assert stored("sg1")["result"] == 2
    for signal in (signals.task_prerun, signals.task_postrun, signals.task_failure):
        for receiver in list(signal._receivers):
            if receiver.__module__ == "signals_setup":
                signal.disconnect(receiver)
