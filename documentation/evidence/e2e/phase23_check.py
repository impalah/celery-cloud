"""Phases 2-4 against a real Celery client: API, retries, eta, canvas."""
import time

from celery import chain, chord, group
from e2e_client import (add, always_fails, auto_flaky, flaky, ignores, natural_add, on_error,
                        progress, raises_value, rejects, rejects_for_good, total)

def section(t): print(f"\n=== {t}")

section("natural call convention + retries")
print("natural_add(2, y=5) ->", natural_add.apply_async((2,), {"y": 5}).get(timeout=30))
t = time.time(); r = flaky.apply_async(); print("flaky ->", r.get(timeout=60), "| %.1fs" % (time.time() - t), "| state", r.state)
try: always_fails.apply_async().get(timeout=60)
except Exception as e: print("always_fails ->", type(e).__name__, e.args)
print("auto_flaky ->", auto_flaky.apply_async(("v",), {"suffix": "!"}).get(timeout=60))

section("update_state (custom PROGRESS state)")
r = progress.apply_async((3,)); seen = []
while not r.ready():
    if r.state == "PROGRESS" and r.info not in seen: seen.append(r.info)
    time.sleep(0.4)
print("progress seen:", seen, "| final:", r.get())

section("Ignore / Reject")
r = ignores.apply_async(); time.sleep(4); print("ignores state/info:", r.state, r.info)
print("rejects (requeue) ->", rejects.apply_async().get(timeout=60))
r = rejects_for_good.apply_async(); time.sleep(4); print("rejects_for_good state:", r.state)

section("eta / countdown")
t = time.time(); print("countdown=6 ->", add.apply_async((1, 1), countdown=6).get(timeout=60), "after %.1fs" % (time.time() - t))

section("link / link_error")
child = add.s(10); cres = child.freeze(); add.apply_async((1, 2), link=child); print("link child (3 + 10) ->", cres.get(timeout=60))
handler = on_error.s(); hres = handler.freeze(); failing = raises_value.apply_async(link_error=handler)
print("errback ->", hres.get(timeout=60), "| failing id", failing.id[:8])

section("chain")
c = chain(add.s(1, 2), add.s(10), add.s(100)).apply_async(); print("chain result:", c.get(timeout=60), "| parents:", [p.result for p in [c.parent, c.parent.parent]])

section("group + chord")
print("group:", group(add.s(1, 1), add.s(2, 2)).apply_async().get(timeout=60))
ch = chord([add.s(1, 2), add.s(3, 4), add.s(5, 6)])(total.s()); print("chord total:", ch.get(timeout=60))
ch2 = chord([add.s(1, 2), raises_value.s()])(total.s())
try: ch2.get(timeout=60)
except Exception as e: print("chord with failing header ->", type(e).__module__ + "." + type(e).__name__, str(e)[:90])
