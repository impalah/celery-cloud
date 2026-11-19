"""Compare an item written by Celery's own DynamoDB backend with one written by the runner.

Run after driver.py, with the same environment (env.sh) and the same moto server:
  python ttl_compat.py client_ttl.py     # client_ttl.py = client_example.py + ?ttl_seconds=3600
"""
import re, sys, time, boto3
Q = open("queue_url.txt").read().strip()
src = re.sub(r'QUEUE_URL = ".*"', f'QUEUE_URL = "{Q}"', open(sys.argv[1]).read())
ns = {"__name__": "c"}; exec(compile(src, "c", "exec"), ns)
ns["app"].backend.set("celery-task-meta-written-by-celery", b'{"status": "SUCCESS"}')  # Celery's own write path
items = {i["id"]["S"]: i for i in boto3.client("dynamodb").scan(TableName="lambda-runner-tasks")["Items"]}
celery_item = next(v for k, v in items.items() if "written-by-celery" in k)
runner_item = next(v for k, v in items.items() if "written-by-celery" not in k)
shape = lambda item: {k: list(v)[0] for k, v in item.items()}
print("celery:", shape(celery_item)); print("runner:", shape(runner_item))
print("same attributes and types:", shape(celery_item) == shape(runner_item))
now = int(time.time())
print("celery ttl - now:", int(celery_item["ttl"]["N"]) - now, "| runner ttl - now:", int(runner_item["ttl"]["N"]) - now)
