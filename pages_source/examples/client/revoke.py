"""Revoke a task: the optional helper that needs the runner's help."""

import time

from celery_app import add, app, long_job
from celery_cloud.client import install

# Once, after configuring the app: result.revoke() / app.control.revoke() now write
# the revocation to the result backend, where the runner reads it
install(app)

# 1. A task that has not started never starts
held = add.apply_async(args=(1, 2), countdown=60)  # held by the runner until it is due
held.revoke()
time.sleep(2)
print(held.state)  # REVOKED

# 2. A running task is only flagged: it stops if its code looks at is_revoked()
job = long_job.apply_async(args=(20,))
time.sleep(3)
job.revoke()  # terminate=True is accepted, but a running task is never killed
print(job.get(timeout=60))  # stopped after 6 steps because it was revoked
