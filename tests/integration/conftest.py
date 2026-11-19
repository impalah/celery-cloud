"""Shared fixtures of the integration tests: a simulated AWS (moto), nothing real."""

import pytest
from moto import mock_aws

from celery_cloud.models.task_model import TaskModel

REGION = "eu-west-1"


@pytest.fixture(autouse=True)
def aws(monkeypatch):
    """Fake credentials (nothing real can be reached) and an empty table."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)
    with mock_aws():
        TaskModel.Meta.region = REGION
        TaskModel.create_table(billing_mode="PAY_PER_REQUEST", wait=True)
        yield


QUEUE_NAME = "my-queue"


class Queue:
    """The queue the runner sends to (the one of ``eventSourceARN``)."""

    def __init__(self) -> None:
        import boto3

        self.client = boto3.client("sqs", region_name=REGION)
        self.client.create_queue(QueueName=QUEUE_NAME)
        self.url = self.client.get_queue_url(QueueName=QUEUE_NAME)["QueueUrl"]

    def receive(self) -> list[dict]:
        """Every message that can be received now (delayed ones are not)."""
        messages = []
        while True:
            batch = self.client.receive_message(
                QueueUrl=self.url, MaxNumberOfMessages=10, VisibilityTimeout=0
            ).get("Messages", [])
            if not batch:
                return messages
            for message in batch:
                self.client.delete_message(
                    QueueUrl=self.url, ReceiptHandle=message["ReceiptHandle"]
                )
            messages.extend(batch)

    def delayed(self) -> int:
        attributes = self.client.get_queue_attributes(
            QueueUrl=self.url, AttributeNames=["ApproximateNumberOfMessagesDelayed"]
        )["Attributes"]
        return int(attributes["ApproximateNumberOfMessagesDelayed"])


@pytest.fixture
def queue(aws):
    """A simulated queue, and a fresh SQS client cache for the runner."""
    from celery_cloud import messaging

    messaging._sqs_client.cache_clear()
    yield Queue()
    messaging._sqs_client.cache_clear()
