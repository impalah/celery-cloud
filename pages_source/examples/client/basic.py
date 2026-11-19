"""Send a task and wait for its result."""

from celery_app import add

# Positional and keyword arguments both reach the task
result = add.apply_async(args=(10, 3), kwargs={"extra": 5})
print(f"Sent task {result.id}")

# Always use a timeout: if the runner dies the task stays in STARTED forever
print(f"Result: {result.get(timeout=60)}")  # 18
print(f"State:  {result.state}")  # SUCCESS
