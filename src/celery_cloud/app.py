from typing import Any
from time import sleep
from celery_cloud.core.entities import CeleryTask, LambdaResponse
from celery_cloud.core.sqs_processor import sqs_processor
from celery_cloud.tasks_configuration import TASKS
from celery_cloud.core.logging import logger


@sqs_processor
def lambda_handler(celery_task: CeleryTask) -> Any:
    """Executes a Celery task and returns result

    Args:
        celery_task (CeleryTask): Celery object with the task to execute.

    Returns:
        Any: Result of the operation.
    """

    if celery_task.task not in TASKS:
        logger.error(f"Task '{celery_task.task}' not supported")

        return LambdaResponse(
            status="error",
            message=f"Task '{celery_task.task}' not supported",
            details=f"Task '{celery_task.task}' not supported",
        ).model_dump()

    # Simulate execution of Celery task adding a delay
    # TODO: Use strategy pattern to execute different tasks
    sleep(3)

    # Call function with args and kwargs
    return TASKS[celery_task.task](celery_task.args, celery_task.kwargs)
