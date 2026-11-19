import base64, json, os, re, sys, threading, time, traceback
sys.path.insert(0, os.getcwd())
QUEUE_URL = open("queue_url.txt").read().strip()
os.environ.update(
    TASKS=json.dumps({"tasks.add": "task://my_tasks/add", "tasks.boom": "task://my_tasks/boom"}),
    CELERY_BACKEND_TABLE="lambda-runner-tasks", CELERY_BACKEND_REGION="eu-central-1", LOG_LEVEL="WARNING",
)
import boto3

# 1. the README client, verbatim, only pointing the queue url to moto
src = open(sys.argv[1] if len(sys.argv) > 1 else "client_example.py").read()
src = re.sub(r'QUEUE_URL = ".*"', f'QUEUE_URL = "{QUEUE_URL}"', src)
ns = {"__name__": "client"}
exec(compile(src, "client_example.py", "exec"), ns)
app, add = ns["app"], ns["add"]

@app.task(name="tasks.boom")
def boom(): raise NotImplementedError

from celery_cloud.runners.aws_lambda import lambda_handler

sqs = boto3.client("sqs")

def receive_event(wait=10):
    r = sqs.receive_message(QueueUrl=QUEUE_URL, MaxNumberOfMessages=10, WaitTimeSeconds=wait,
                            AttributeNames=["All"], VisibilityTimeout=30)
    msgs = r.get("Messages", [])
    return {"Records": [{
        "messageId": m["MessageId"], "receiptHandle": m["ReceiptHandle"], "body": m["Body"],
        "attributes": {k: m["Attributes"][k] for k in ("ApproximateReceiveCount", "SentTimestamp", "ApproximateFirstReceiveTimestamp")},
        "eventSource": "aws:sqs", "eventSourceARN": "arn:aws:sqs:eu-central-1:123456789012:lambda-runner-queue",
    } for m in msgs]}, msgs

def run_runner():
    event, msgs = receive_event()
    print(f"   runner received {len(msgs)} message(s)")
    out = lambda_handler(event, None)
    for m in msgs: sqs.delete_message(QueueUrl=QUEUE_URL, ReceiptHandle=m["ReceiptHandle"])
    return event, out

def section(t): print(f"\n=== {t}")

section("A. success: add(10, 3) with a local task")
res = add.apply_async((10, 3)); print("   sent", res.id)
event_a, out = run_runner(); print("   handler:", {k: out[k] for k in ("status","processed_messages","failed_messages","skipped_messages","batchItemFailures")})
print("   client state:", res.state, "| result:", res.get(timeout=20))

section("B. failure: the task raises")
res2 = boom.apply_async(); print("   sent", res2.id)
_, out = run_runner(); print("   handler:", {k: out[k] for k in ("processed_messages","failed_messages","batchItemFailures")})
print("   client state:", res2.state)
try: res2.get(timeout=20); print("   !! get() did not raise")
except Exception as e: print(f"   get() raised {type(e).__module__}.{type(e).__name__}: {e}")
print("   traceback stored:", bool(res2.traceback))

section("C. duplicate delivery of task A")
out = lambda_handler(event_a, None); print("   handler:", {k: out[k] for k in ("processed_messages","skipped_messages")}, out["skipped_tasks"])

section("D. ttl field written by the Celery client vs the runner")
ddb = boto3.client("dynamodb")
for item in ddb.scan(TableName="lambda-runner-tasks")["Items"]:
    print("   key", item["id"]["S"][:40], "| attributes:", sorted(item))
