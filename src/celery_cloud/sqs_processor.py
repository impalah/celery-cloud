import json
from typing import Any, Callable, Dict, List, TypeVar
from pydantic import ValidationError
from celery_cloud.entities import SQSEvent, CeleryTask, ProcessedTask, FailedTask, LambdaResponse

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
            # Validate event with pydantic
            sqs_event: SQSEvent = SQSEvent(**event)

            for record in sqs_event.Records:
                try:
                    # Decode SQS message body
                    task_data: Dict[str, Any] = json.loads(record.body)
                    celery_task: CeleryTask = CeleryTask(**task_data)

                    print(f"Executing task: {celery_task.task} with ID {celery_task.id}")

                    # Call decorated function with the arguments
                    result: Any = func(celery_task)

                    processed_tasks.append(
                        ProcessedTask(task_id=celery_task.id, status="SUCCESS", result=result)
                    )

                except json.JSONDecodeError as e:
                    failed_tasks.append(
                        FailedTask(
                            message_id=record.messageId,
                            error=f"JSONDecodeError: {str(e)}"
                        )
                    )
                except ValidationError as e:
                    failed_tasks.append(
                        FailedTask(
                            message_id=record.messageId,
                            error=f"ValidationError: {e.json()}"
                        )
                    )
                except Exception as e:
                    failed_tasks.append(
                        FailedTask(
                            task_id=celery_task.id if 'celery_task' in locals() else None,
                            message_id=record.messageId,
                            error=str(e)
                        )
                    )

        except ValidationError as e:
            return LambdaResponse(
                status="error",
                message="Invalid SQS event format",
                details=e.json()
            ).model_dump()

        return LambdaResponse(
            status="completed",
            processed_messages=len(processed_tasks),
            failed_messages=len(failed_tasks),
            processed_tasks=processed_tasks if processed_tasks else None,
            failed_tasks=failed_tasks if failed_tasks else None
        ).model_dump()

    return wrapper  # Return decorated function
