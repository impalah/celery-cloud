from celery import Celery

REGION = "eu-central-1"
QUEUE_NAME = "lambda-runner-queue"
QUEUE_URL = "https://sqs.eu-central-1.amazonaws.com/123456789012/lambda-runner-queue"
TABLE = "lambda-runner-tasks"

app = Celery("task_client")
app.conf.update(
    broker_url="sqs://",
    result_backend=f"dynamodb://@{REGION}/{TABLE}",
    task_default_queue=QUEUE_NAME,
    broker_connection_retry_on_startup=True,
    broker_transport_options={
        "region": REGION,
        # the queue must already exist: the client does not create it
        "predefined_queues": {QUEUE_NAME: {"url": QUEUE_URL}},
    },
)


# The name is what the runner looks up in TASKS: always set it explicitly.
@app.task(name="tasks.add")
def add(x: int, y: int) -> int:
    """Declaration only: the body never runs on the client."""
    raise NotImplementedError


if __name__ == "__main__":
    result = add.apply_async((10, 3))
    print(f"Sent task {result.id}")
    print(f"Result: {result.get(timeout=60)}")
