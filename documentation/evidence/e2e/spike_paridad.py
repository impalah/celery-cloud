import sys, time
sys.path.insert(0, "/home/linus/projects/celery-cloud/pages_source/examples/client")
from celery import chain, group, chord
from celery_app import add, app, subtract

print("--- group")
g = group(add.s(1, 2), add.s(3, 4)).apply_async()
print("group result:", g.get(timeout=30))

print("--- chain add(1,2) | add(10)")
c = chain(add.s(1, 2), add.s(10)).apply_async()
time.sleep(8)
print("last state:", c.state, "| parent state:", c.parent.state if c.parent else None, "| parent result:", c.parent.result if c.parent else None)

print("--- chord (add(1,2), add(3,4)) -> add(.. )")
@app.task(name="calculator.add")
def _unused(): ...
try:
    ch = chord([add.s(1, 2), add.s(3, 4)])(subtract.s())
    time.sleep(8)
    print("chord body state:", ch.state, "| header states:", [r.state for r in ch.parent.results] if ch.parent else None)
except Exception as e:
    print("chord error:", type(e).__name__, e)

print("--- exception type fidelity")
r = subtract.apply_async(args=(5,))
try: r.get(timeout=30)
except Exception as e: print("client got:", type(e).__module__, type(e).__name__)
print("--- countdown=20")
t = time.time(); r = add.apply_async(args=(1, 1), countdown=20); print("result:", r.get(timeout=30), "after %.1fs (countdown asked 20s)" % (time.time()-t))
