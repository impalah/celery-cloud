import ast
import base64
import json
from typing import Any, Callable, Dict, List, TypeVar
from pydantic import ValidationError
from ksuid import Ksuid
from celery_cloud.core.logging import trace_id_context, logger
from celery_cloud.core.entities import SQSEvent, CeleryTask, ProcessedTask, FailedTask, LambdaResponse, CeleryTaskResult, SQSMessage
from celery_cloud.core.models.celery_task_model import CeleryTaskModel

F = TypeVar("F", bound=Callable[..., Any])  # Generic type for functions


def sqs_processor(func: F) -> F:
    """Decorator for Processing SQS events .

    Args:
        func (F): Function to execute.

    Returns:
        F: Decorated function.
    """

    def wrapper(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
        processed_tasks: List[ProcessedTask] = []
        failed_tasks: List[FailedTask] = []

        try:

            # Generate KSUID as trace_id
            trace_id = str(Ksuid())
            # Assign trace_id to context
            trace_id_context.set(trace_id)

            # Validate event with pydantic
            sqs_event: SQSEvent = SQSEvent(**event)

            logger.debug(f"Processing lambda event: {sqs_event.model_dump()}")

            for record in sqs_event.Records:
                try:

                    # # Decode SQS message body
                    # task_data: Dict[str, Any] = json.loads(base64.b64decode(record.body).decode())
                    # logger.debug(f"Record data: {task_data}")

                    # celery_task: CeleryTask = CeleryTask(**task_data)
                    # logger.debug(f"Processing task: {celery_task.task} with ID {celery_task.id}")
                    message: Dict[str, Any] = record.get_message()
                    sqs_message: SQSMessage = SQSMessage(body=message["body"], content_encoding=message["content-encoding"], content_type=message["content-type"], headers=message["headers"], properties=message["properties"])
                    logger.debug(f"Processing message: {sqs_message}")


                    # Create CeleryTask object
                    celery_task: CeleryTask = CeleryTask(
                        id=sqs_message.headers.id,
                        task=sqs_message.headers.task,
                        args=ast.literal_eval(sqs_message.headers.argsrepr),  # Safely convert string to list
                        kwargs=ast.literal_eval(sqs_message.headers.kwargsrepr)  # Safely convert string to dict
                    )


                    # Set task status to "PROCESSING" in backend
                    task_model: CeleryTaskModel = CeleryTaskModel.insert_task(task_uuid=celery_task.id)

                    # Call decorated function with the arguments
                    result: Any = func(celery_task)

                    logger.debug(f"Processed task: {celery_task.task} with ID {celery_task.id}")

                    CeleryTaskModel.update_task(
                        celery_task.id,
                        status="SUCCESS",
                        result=result
                    )

                    processed_tasks.append(
                        ProcessedTask(
                            task_id=celery_task.id, status="SUCCESS", result=result
                        )
                    )

                except json.JSONDecodeError as e:
                    logger.error(f"JSONDecodeError processing task {celery_task.task}/{celery_task.id}: {str(e)}")

                    CeleryTaskModel.update_task(
                        celery_task.id,
                        status="FAILURE",
                        result=f"JSONDecodeError: {str(e)}",
                        traceback=e.__traceback__
                    )

                    failed_tasks.append(
                        FailedTask(
                            message_id=record.messageId,
                            error=f"JSONDecodeError: {str(e)}",
                        )
                    )
                except ValidationError as e:
                    # TODO: Add more specific error handling
                    logger.error(f"ValidationError processing task {celery_task.task}/{celery_task.id}: {str(e)}")

                    CeleryTaskModel.update_task(
                        celery_task.id,
                        status="FAILURE",
                        result=f"ValidationError: {e.json()}",
                        traceback=e.__traceback__
                    )

                    failed_tasks.append(
                        FailedTask(
                            message_id=record.messageId,
                            error=f"ValidationError: {e.json()}",
                        )
                    )
                except Exception as e:
                    logger.error(f"Error processing task {celery_task.task if 'celery_task' in locals() else None}/{celery_task.id if 'celery_task' in locals() else None}: {str(e)}")

                    CeleryTaskModel.update_task(
                        celery_task.id,
                        status="FAILURE",
                        result=f"Exception: {str(e)}",
                        traceback=e.__traceback__
                    )

                    failed_tasks.append(
                        FailedTask(
                            task_id=(
                                celery_task.id if "celery_task" in locals() else None
                            ),
                            message_id=record.messageId,
                            error=str(e),
                        )
                    )

        except ValidationError as e:

            logger.error(f"Invalid SQS event format: {e.json()}")

            # Clear context before finishing the function
            trace_id_context.set(None)

            return LambdaResponse(
                status="error", message="Invalid SQS event format", details=e.json()
            ).model_dump()

        # Clear context before finishing the function
        trace_id_context.set(None)

        return LambdaResponse(
            status="completed",
            processed_messages=len(processed_tasks),
            failed_messages=len(failed_tasks),
            processed_tasks=processed_tasks if processed_tasks else None,
            failed_tasks=failed_tasks if failed_tasks else None,
        ).model_dump()

    return wrapper  # Return decorated function

