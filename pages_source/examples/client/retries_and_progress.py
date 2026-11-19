"""Retries, progress reports and delayed execution."""

import time

from celery_app import export_report, fetch, import_rows, sync_account

# 1. A task that retries by itself: the client only sees the final result
result = fetch.apply_async(args=("https://flaky.example/page",))
print(result.get(timeout=120))  # {'url': ..., 'attempts': 3, 'bytes': ...}

# 2. autoretry_for with exponential backoff
print(sync_account.apply_async(args=(7,), kwargs={"attempts_needed": 3}).get(timeout=120))

# 3. Progress: poll the state while the task works
job = import_rows.apply_async(args=(5,))
while not job.ready():
    if job.state == "PROGRESS":
        info = job.info  # the meta of update_state()
        print(f"{info['done']}/{info['of']} rows")
    time.sleep(0.3)
print(job.get())  # {'imported': 5}

# 4. A soft time limit set by the task, or per call by the client
print(export_report.apply_async(args=(10,)).get(timeout=60))  # partial report
print(export_report.apply_async(args=(0.1,), soft_time_limit=30).get(timeout=60))

# 5. Delayed execution: the runner holds the task until it is due
started = time.monotonic()
later = fetch.apply_async(args=("https://example.com",), countdown=10)
print(later.state)  # PENDING until the task is picked up
later.get(timeout=120)
print(f"ran after {time.monotonic() - started:.0f} s")  # about 10
