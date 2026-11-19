"""Phase 1 against a real Celery client: original exceptions, time limits, extended meta."""
import time

from celery.exceptions import SoftTimeLimitExceeded, TimeLimitExceeded
from e2e_client import add, app, raises_custom, raises_value, slow

print("--- original exception type")
try:
    raises_value.apply_async().get(timeout=30)
except ValueError as e:
    print("client caught ValueError:", e.args)
try:
    raises_custom.apply_async().get(timeout=30)
except Exception as e:
    print("custom exception:", type(e).__module__ + "." + type(e).__name__, e.args)

print("--- soft time limit (1 s) on a 10 s task")
t = time.time()
try:
    slow.apply_async(soft_time_limit=1).get(timeout=30)
except SoftTimeLimitExceeded as e:
    print("client caught SoftTimeLimitExceeded after %.1fs:" % (time.time() - t), e)

print("--- hard time limit (1 s)")
try:
    slow.apply_async(time_limit=1).get(timeout=30)
except TimeLimitExceeded as e:
    print("client caught TimeLimitExceeded:", e)

print("--- extended meta (client result_extended)")
r = add.apply_async((2, 3)); r.get(timeout=30)
print("name:", r.name, "| args:", r.args, "| worker:", r.worker, "| queue:", r.queue, "| retries:", r.retries)
