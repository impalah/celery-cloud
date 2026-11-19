"""Celery client of the end-to-end checks."""
import os

from celery import Celery

QUEUE_URL = os.environ["CELERY_QUEUE_URL"]
app = Celery("e2e")
app.conf.update(
    broker_url="sqs://",
    result_backend="dynamodb://@eu-central-1/lambda-runner-tasks",
    task_default_queue="lambda-runner-queue",
    broker_connection_retry_on_startup=True,
    broker_transport_options={"region": "eu-central-1", "predefined_queues": {"lambda-runner-queue": {"url": QUEUE_URL}}},
    result_extended=bool(os.environ.get("E2E_EXTENDED")),
    task_serializer=os.environ.get("E2E_SERIALIZER", "json"),
    result_serializer=os.environ.get("E2E_SERIALIZER", "json"),
    accept_content=["json", "msgpack", "yaml"],
    task_compression=os.environ.get("E2E_COMPRESSION") or None,
)
if os.environ.get("E2E_INSTALL_REVOKE"):
    from celery_cloud.client import install

    install(app)


@app.task(name="e2e.add")
def add(x, y): ...


@app.task(name="e2e.raises_value")
def raises_value(): ...


@app.task(name="e2e.raises_custom")
def raises_custom(): ...


@app.task(name="e2e.slow")
def slow(): ...


@app.task(name="e2e.flaky")
def flaky(): ...


@app.task(name="e2e.always_fails")
def always_fails(): ...


@app.task(name="e2e.auto_flaky")
def auto_flaky(value, suffix=""): ...


@app.task(name="e2e.progress")
def progress(steps): ...


@app.task(name="e2e.natural_add")
def natural_add(x, y=0): ...


@app.task(name="e2e.ignores")
def ignores(): ...


@app.task(name="e2e.rejects")
def rejects(): ...


@app.task(name="e2e.rejects_for_good")
def rejects_for_good(): ...


@app.task(name="e2e.total")
def total(values): ...


@app.task(name="e2e.on_error")
def on_error(task_id): ...


@app.task(name="e2e.watches_revocation")
def watches_revocation(): ...
