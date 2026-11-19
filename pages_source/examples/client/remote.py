"""Call a task that runs on an existing Lambda function (lambda:// route)."""

from celery_app import remote_sum

result = remote_sum.apply_async(args=(22, 31))
print(result.get(timeout=60))  # 53
