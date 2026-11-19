import importlib
import os
from typing import Any

from celery_cloud.entities import Task, TaskRoute
from celery_cloud.exceptions import TaskExecutionException
from celery_cloud.logging import logger
from celery_cloud.runners.task_execution_strategy import TaskExecutionStrategy
from celery_cloud.tasks import (
    TaskOptions,
    TaskRequest,
    call_task_function,
    get_options,
)


def load_function(route: TaskRoute) -> Any:
    """Import the function of a ``task://<module>/<function>`` route.

    Module and function come from the TASKS setting (trusted, deployed with the
    runner), never from the message.
    """
    module = importlib.import_module(route.module)
    return getattr(module, route.function)


def task_options(route: TaskRoute) -> TaskOptions | None:
    """The ``@task`` options of a local route (None for a plain function).

    Best effort: if the function cannot be imported, None is returned and executing
    the task reports the real error.
    """
    if route.scheme != "task" or not route.module or not route.function:
        return None
    try:
        return get_options(load_function(route))
    except Exception:
        return None


class LocalTaskExecutionStrategy(TaskExecutionStrategy):
    """Run the task as a python function packaged with the runner.

    The route is ``task://<module>/<function>``. The function is called with
    **two positional parameters**: the list of positional arguments and the
    dict of keyword arguments, i.e. ``function(args, kwargs)``. A function decorated
    with ``celery_cloud.task`` is called with its natural arguments instead (see
    ``celery_cloud.tasks``).
    """

    def execute(self, task: Task, route: TaskRoute) -> Any:
        if not route.module or not route.function:
            raise TaskExecutionException(
                message=f"Invalid local route for task {task.task}",
                detail="expected task://<module>/<function>",
            )

        logger.debug(f"Executing local task {task.task} with ID {task.id}")

        function = load_function(route)

        logger.debug(f"Function {function} imported from module {route.module}")

        request = TaskRequest(
            id=task.id,
            task=task.task,
            args=task.args,
            kwargs=task.kwargs,
            retries=task.retries or 0,
            eta=task.eta,
            expires=task.expires,
            parent_id=task.parent_id,
            root_id=task.root_id,
            group=task.group,
            group_index=task.group_index,
            hostname=os.getenv("AWS_LAMBDA_FUNCTION_NAME", "celery-cloud"),
            delivery_info={"routing_key": task.queue},
            callbacks=task.callbacks,
            errbacks=task.errbacks,
            chain=task.chain,
            chord=task.chord,
            time_limit=task.time_limit,
            soft_time_limit=task.soft_time_limit,
        )
        return call_task_function(function, request)
