"""Tasks of the end-to-end checks (packaged with the runner)."""
import time


class InsufficientFunds(Exception):
    pass


def add(args, kwargs):
    return sum(args)


def raises_value(args, kwargs):
    raise ValueError("bad value", 42)


def raises_custom(args, kwargs):
    raise InsufficientFunds("balance too low")


def slow(args, kwargs):
    time.sleep(10)
    return "never"


# --- Celery-like API (decorated tasks) and canvas helpers ---------------------
from celery_cloud import Ignore, Reject, task  # noqa: E402

_attempts: dict[str, int] = {}


@task(bind=True, max_retries=3, default_retry_delay=1)
def flaky(self):
    """Fails twice, succeeds on the third attempt."""
    if self.request.retries < 2:
        raise self.retry(exc=ConnectionError(f"attempt {self.request.retries}"))
    return f"ok after {self.request.retries + 1} attempts"


@task(bind=True, max_retries=1, default_retry_delay=0)
def always_fails(self):
    raise self.retry(exc=RuntimeError("never works"))


@task(autoretry_for=(ConnectionError,), retry_backoff=True, retry_jitter=False,
      max_retries=2, default_retry_delay=0)
def auto_flaky(value, suffix=""):
    key = f"auto-{value}"
    _attempts[key] = _attempts.get(key, 0) + 1
    if _attempts[key] < 3:
        raise ConnectionError("not yet")
    return f"{value}{suffix} after {_attempts[key]} calls"


@task(bind=True)
def progress(self, steps):
    for i in range(steps):
        self.update_state(state="PROGRESS", meta={"done": i + 1, "of": steps})
        time.sleep(1.2)
    return "finished"


@task
def natural_add(x, y=0):
    return x + y


@task(bind=True)
def ignores(self):
    self.update_state(state="CUSTOM", meta="set by hand")
    raise Ignore()


@task(bind=True)
def rejects(self):
    _attempts["reject"] = _attempts.get("reject", 0) + 1
    if _attempts["reject"] == 1:
        raise Reject("try again", requeue=True)
    return f"ran after {_attempts['reject']} receives"


@task
def rejects_for_good():
    raise Reject("not for me", requeue=False)


def total(args, kwargs):
    return sum(args[0])


def on_error(args, kwargs):
    return f"handled {args[0]}"


@task(bind=True)
def watches_revocation(self):
    """Polls is_revoked(): cooperative cancellation."""
    for _ in range(30):
        if self.is_revoked():
            return "stopped because it was revoked"
        time.sleep(0.5)
    return "was not revoked"
