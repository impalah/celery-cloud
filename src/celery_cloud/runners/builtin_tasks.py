"""Celery's built-in tasks that run other tasks: ``celery.map`` and ``celery.starmap``.

``task.map([...])``, ``task.starmap([...])`` and ``task.chunks(...)`` (which the client
expands into several ``celery.starmap`` messages) are executed by a Celery worker as
tasks of their own. The runner runs them the same way: it calls the task named in the
embedded signature once per item, in this invocation, and returns the list of results.
The named task must be listed in ``TASKS`` like any other.
"""

from typing import Any

from celery_cloud.entities import Task, TaskRoute
from celery_cloud.exceptions import TaskExecutionException
from celery_cloud.settings import settings

from .task_executor import TaskExecutor

# built-in name -> True when every item is a sequence of positional arguments
BUILTIN_TASKS = {"celery.map": False, "celery.starmap": True}


def run_builtin(task: Task, executor: TaskExecutor) -> list[Any]:
    """Run ``celery.map`` / ``celery.starmap`` and return the results in order."""
    starred = BUILTIN_TASKS[task.task]
    signature = task.kwargs.get("task")
    items = task.kwargs.get("it")
    if not isinstance(signature, dict) or "task" not in signature:
        raise TaskExecutionException(
            message=f"Invalid {task.task} message", detail="missing the task signature"
        )
    if not isinstance(items, list):
        raise TaskExecutionException(
            message=f"Invalid {task.task} message", detail="missing the item list"
        )

    name = str(signature["task"])
    if name not in settings.TASKS:
        raise NotImplementedError(f"Task '{name}' not supported")
    route = TaskRoute.from_url(settings.TASKS[name])
    own_args = list(signature.get("args") or [])
    own_kwargs = dict(signature.get("kwargs") or {})

    results: list[Any] = []
    for item in items:
        if starred and not isinstance(item, list | tuple):
            raise TaskExecutionException(
                message=f"Invalid {task.task} message",
                detail=f"item {item!r} is not a list of arguments",
            )
        # like Celery: the item's arguments first, then the signature's own
        call_args = [*(item if starred else [item]), *own_args]
        subtask = Task(
            id=task.id,
            task=name,
            args=call_args,
            kwargs=own_kwargs,
            retries=0,
            queue=task.queue,
        )
        results.append(executor.execute(subtask, route))
    return results
