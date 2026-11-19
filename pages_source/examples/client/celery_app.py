"""Celery client configuration shared by the examples.

The client only *declares* the tasks (name and signature). The bodies never run
here: they run on the runner, wherever ``TASKS`` points.
"""

import os
from typing import Any

from celery import Celery

REGION = os.environ.get("AWS_REGION", "eu-central-1")
QUEUE_NAME = os.environ.get("CELERY_QUEUE_NAME", "lambda-runner-queue")
QUEUE_URL = os.environ["CELERY_QUEUE_URL"]  # https://sqs.<region>.amazonaws.com/<account>/<queue>
TABLE = os.environ.get("CELERY_BACKEND_TABLE", "lambda-runner-tasks")

app = Celery("task_client")
app.conf.update(
    broker_url="sqs://",
    result_backend=f"dynamodb://@{REGION}/{TABLE}",
    task_default_queue=QUEUE_NAME,
    broker_connection_retry_on_startup=True,
    broker_transport_options={
        "region": REGION,
        # The queue must already exist: the client does not create it
        "predefined_queues": {QUEUE_NAME: {"url": QUEUE_URL}},
    },
)


# The name must be exactly the key used in the TASKS setting of the runner
@app.task(name="calculator.add")
def add(x: int, y: int, extra: int = 0) -> int:
    raise NotImplementedError


@app.task(name="calculator.subtract")
def subtract(*values: int) -> int:
    raise NotImplementedError


@app.task(name="calculator.divide")
def divide(x: int, y: int) -> float:
    raise NotImplementedError


@app.task(name="reports.summarize")
def summarize(request: dict[str, Any]) -> dict[str, Any]:
    raise NotImplementedError


@app.task(name="remote.sum")
def remote_sum(*values: int) -> int:
    raise NotImplementedError


@app.task(name="calculator.total")
def total(values: list[int]) -> int:
    raise NotImplementedError


@app.task(name="calculator.report_error")
def report_error(task_id: str) -> str:
    raise NotImplementedError


@app.task(name="jobs.fetch")
def fetch(url: str) -> dict[str, Any]:
    raise NotImplementedError


@app.task(name="jobs.sync_account")
def sync_account(account_id: int, attempts_needed: int = 1) -> str:
    raise NotImplementedError


@app.task(name="jobs.import_rows")
def import_rows(rows: int) -> dict[str, Any]:
    raise NotImplementedError


@app.task(name="jobs.export_report")
def export_report(seconds: float) -> str:
    raise NotImplementedError


@app.task(name="jobs.long_job")
def long_job(steps: int) -> str:
    raise NotImplementedError
