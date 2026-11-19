"""Phase 5 against a real Celery client: revoke, serializers and compression."""
import os
import time

from e2e_client import add, natural_add, slow, watches_revocation

print("serializer:", os.environ.get("E2E_SERIALIZER", "json"), "| compression:", os.environ.get("E2E_COMPRESSION"))
print("add ->", add.apply_async((20, 22)).get(timeout=60))
print("natural_add ->", natural_add.apply_async((1,), {"y": 2}).get(timeout=60))
try:
    from e2e_client import raises_value
    raises_value.apply_async().get(timeout=60)
except ValueError as e:
    print("failure ->", type(e).__name__, e.args)

if os.environ.get("E2E_INSTALL_REVOKE"):
    print("--- revoke")
    # 1. a task that has not started: revoke before the runner sees it
    r = add.apply_async((1, 2), countdown=3)  # held by the eta, so it has not started
    r.revoke()
    time.sleep(6)
    print("revoked before start -> state:", r.state)
    try:
        r.get(timeout=5)
    except Exception as e:
        print("   get() ->", type(e).__module__ + "." + type(e).__name__)
    # 2. cooperative: a running task notices
    w = watches_revocation.apply_async()
    time.sleep(3)
    w.revoke(terminate=True)
    print("running task ->", w.get(timeout=60) if w.state != "REVOKED" else "REVOKED state (flag only)")
