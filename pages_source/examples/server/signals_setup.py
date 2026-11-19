"""Signal receivers, loaded once when the function starts.

Put the module in the ``INIT_MODULES`` setting (``INIT_MODULES=signals_setup``) so the
receivers are connected before the first task runs.
"""

import time

from celery_cloud.logging import logger
from celery_cloud.signals import task_failure, task_postrun, task_prerun

_started: dict[str, float] = {}


@task_prerun.connect
def remember_start(task_id=None, task=None, **kwargs):
    _started[task_id] = time.monotonic()


@task_postrun.connect
def log_duration(task_id=None, task=None, state=None, **kwargs):
    seconds = time.monotonic() - _started.pop(task_id, time.monotonic())
    logger.info("{} [{}] {} in {:.2f} s", task, task_id, state, seconds)


@task_failure.connect
def alert(task_id=None, task=None, exception=None, **kwargs):
    # send it to your alerting system here
    logger.error("{} [{}] failed: {!r}", task, task_id, exception)
