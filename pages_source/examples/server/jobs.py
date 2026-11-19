"""Tasks written with the Celery-like API (``@task``).

Unlike the plain ``f(args, kwargs)`` functions of ``calculator.py``, a decorated task
is called with its natural arguments and can be *bound*: ``self`` gives access to the
request, ``retry()``, ``update_state()`` and ``is_revoked()``.
"""

import time

from celery_cloud import SoftTimeLimitExceeded, task
from celery_cloud.logging import logger


@task(bind=True, max_retries=3, default_retry_delay=5)
def fetch(self, url: str) -> dict:
    """Pretend to download a page; ``flaky`` URLs fail twice before working."""
    if "flaky" in url and self.request.retries < 2:
        # a retry: the runner sends the same task again after 5 seconds
        raise self.retry(exc=ConnectionError(f"cannot reach {url}"))
    return {
        "url": url,
        "attempts": self.request.retries + 1,
        "bytes": len(url) * 100,
    }


@task(
    autoretry_for=(ConnectionError,),  # retry without writing try/except
    retry_backoff=True,  # 1 s, 2 s, 4 s... (with jitter), at most...
    retry_backoff_max=60,  # ...60 s between attempts
    max_retries=5,
)
def sync_account(account_id: int, attempts_needed: int = 1) -> str:
    """A call that raises ``ConnectionError`` until it is retried enough times."""
    if sync_account.calls.get(account_id, 0) < attempts_needed - 1:
        sync_account.calls[account_id] = sync_account.calls.get(account_id, 0) + 1
        raise ConnectionError("the service is down")
    return f"account {account_id} synchronised"


sync_account.calls = {}  # type: ignore[attr-defined]


@task(bind=True)
def import_rows(self, rows: int) -> dict:
    """Report progress while working: the client reads it with ``result.info``."""
    for done in range(1, rows + 1):
        time.sleep(0.2)  # the real work for one row
        self.update_state(state="PROGRESS", meta={"done": done, "of": rows})
    return {"imported": rows}


@task(bind=True, soft_time_limit=2)
def export_report(self, seconds: float) -> str:
    """Stopped by the soft time limit; it can still return something useful."""
    try:
        time.sleep(seconds)  # the real work
        return "complete report"
    except SoftTimeLimitExceeded:
        logger.warning("report {} ran out of time", self.request.id)
        return "partial report (stopped by the soft time limit)"


@task(bind=True)
def long_job(self, steps: int) -> str:
    """Cooperative cancellation: look at ``is_revoked()`` between the steps."""
    for step in range(steps):
        if self.is_revoked():
            return f"stopped after {step} steps because it was revoked"
        time.sleep(0.5)  # the real work of one step
    return f"finished all {steps} steps"
