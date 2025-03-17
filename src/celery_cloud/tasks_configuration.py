"""Define the tasks that can be executed by the lambda function.
"""

from typing import Any, Dict, Callable
from celery_cloud.domain.sumar import sumar
from celery_cloud.domain.restar import restar


TASKS: Dict[str, Callable[..., Any]] = {
    "celery_cloud.celery.task.sumar": sumar,
    "celery_cloud.celery.task.restar": restar,
}
