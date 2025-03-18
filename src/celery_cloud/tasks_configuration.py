"""Define the tasks that can be executed by the lambda function."""

from typing import Any
from collections.abc import Callable
from celery_cloud.domain.sumar import sumar
from celery_cloud.domain.restar import restar
from celery_cloud.domain.prompt import prompt


TASKS: dict[str, Callable[..., Any]] = {
    "celery_cloud.celery.task.sumar": sumar,
    "celery_cloud.celery.task.restar": restar,
    "celery_cloud.celery.task.prompt": prompt,
}
