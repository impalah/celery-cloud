import json, os, re, sys, urllib.request
sys.path.insert(0, os.getcwd())
import boto3
Q = open("queue_url.txt").read().strip()
src = re.sub(r'QUEUE_URL = ".*"', f'QUEUE_URL = "{Q}"', open("client_example.py").read())
ns = {"__name__": "client"}; exec(compile(src, "c", "exec"), ns)
add = ns["add"]
res = add.apply_async((20, 22)); print("sent", res.id)
sqs = boto3.client("sqs")
m = sqs.receive_message(QueueUrl=Q, MaxNumberOfMessages=1, WaitTimeSeconds=10, AttributeNames=["All"])["Messages"][0]
event = {"Records": [{"messageId": m["MessageId"], "receiptHandle": m["ReceiptHandle"], "body": m["Body"],
  "attributes": {k: m["Attributes"][k] for k in ("ApproximateReceiveCount","SentTimestamp","ApproximateFirstReceiveTimestamp")},
  "eventSource": "aws:sqs", "eventSourceARN": "arn:aws:sqs:eu-central-1:123456789012:lambda-runner-queue"}]}
req = urllib.request.Request("http://localhost:9000/2015-03-31/functions/function/invocations", data=json.dumps(event).encode(), method="POST")
out = json.loads(urllib.request.urlopen(req, timeout=60).read())
print("container response:", {k: out[k] for k in ("status","processed_messages","failed_messages","batchItemFailures")})
sqs.delete_message(QueueUrl=Q, ReceiptHandle=m["ReceiptHandle"])
print("client state:", res.state, "| result:", res.get(timeout=20))
