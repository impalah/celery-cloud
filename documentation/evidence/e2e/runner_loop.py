"""A local 'event source mapping': polls SQS and feeds the handler (moto, no AWS).

Reads TASKS from the environment (set by the caller), imports e2e_tasks from this
folder and gives the handler a fake Lambda context with E2E_REMAINING_MS left.
"""
import io, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import boto3

from celery_cloud.runners.aws_lambda import lambda_handler

url = os.environ["CELERY_QUEUE_URL"]
remaining = int(os.environ.get("E2E_REMAINING_MS", "60000"))
sqs = boto3.client("sqs")


class Context:
    def get_remaining_time_in_millis(self):
        return remaining


while True:
    msgs = sqs.receive_message(
        QueueUrl=url, MaxNumberOfMessages=10, WaitTimeSeconds=2, AttributeNames=["All"], VisibilityTimeout=3
    ).get("Messages", [])
    if not msgs:
        continue
    event = {"Records": [{
        "messageId": m["MessageId"], "receiptHandle": m["ReceiptHandle"], "body": m["Body"],
        "attributes": {k: m["Attributes"][k] for k in ("ApproximateReceiveCount", "SentTimestamp", "ApproximateFirstReceiveTimestamp")},
        "eventSource": "aws:sqs",
        "eventSourceARN": "arn:aws:sqs:eu-central-1:123456789012:lambda-runner-queue",
    } for m in msgs]}
    out = lambda_handler(event, Context())
    print("RUNNER", {k: out.get(k) for k in ("processed_messages", "failed_messages", "skipped_messages", "batchItemFailures")}, flush=True)
    # like an event source mapping with ReportBatchItemFailures: only the messages
    # that are not in batchItemFailures are deleted, the others come back after the
    # visibility timeout
    again = {item["itemIdentifier"] for item in out.get("batchItemFailures", [])}
    for m in msgs:
        if m["MessageId"] not in again:
            sqs.delete_message(QueueUrl=url, ReceiptHandle=m["ReceiptHandle"])
