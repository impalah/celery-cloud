"""Handle failing tasks and tasks that take too long."""

import time

from celery.exceptions import TimeoutError as CeleryTimeoutError
from celery_app import divide, subtract

# 1. A task that raises: get() re-raises an exception with the original message
failing = subtract.apply_async(args=(5,))
try:
    failing.get(timeout=60)
except ValueError as error:  # the ORIGINAL exception type reaches the client
    print(f"Task failed: {error}")  # subtract needs at least 2 values
    print(f"State: {failing.state}")  # FAILURE
    print(failing.traceback)  # traceback captured on the runner

# 2. Check the outcome without raising
other = divide.apply_async(args=(1, 0))
other.wait(timeout=60, propagate=False)
if other.failed():
    print(f"divide failed: {other.result}")

# 3. Poll with your own deadline instead of blocking
pending = divide.apply_async(args=(10, 4))
deadline = time.monotonic() + 30
while not pending.ready():
    if time.monotonic() > deadline:
        # The runner may be down: revoke() would do nothing, so give up locally
        raise SystemExit(f"Task {pending.id} not finished (state {pending.state})")
    print(f"{pending.id}: {pending.state}")
    time.sleep(1)
print(f"divide result: {pending.get()}")  # 2.5

# 4. get(timeout=...) raises celery.exceptions.TimeoutError when nothing arrives
try:
    divide.apply_async(args=(1, 1)).get(timeout=0.001)
except CeleryTimeoutError:
    print("Still running after the timeout")
