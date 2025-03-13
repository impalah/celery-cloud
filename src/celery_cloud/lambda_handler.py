from typing import Any
from time import sleep
from celery_cloud.entities import CeleryTask
from celery_cloud.sqs_processor import sqs_processor


@sqs_processor
def lambda_handler(celery_task: CeleryTask) -> Any:
    """Executes a Celery task and returns result

    Args:
        celery_task (CeleryTask): Celery object with the task to execute.

    Returns:
        Any: Result of the operation.
    """

    # Simulate execution of Celery task adding a delay
    # TODO: Use strategy pattern to execute different tasks
    sleep(5)
    return celery_task.args[0] + celery_task.args[1]
