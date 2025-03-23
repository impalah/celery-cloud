import json
import ast
from typing import Any
from ksuid import Ksuid
from pydantic import ValidationError

from celery_cloud.tasks_configuration import TASKS
from celery_cloud.core.logging import trace_id_context, logger
from celery_cloud.core.entities import (
    SQSEvent,
    CeleryTask,
    ProcessedTask,
    FailedTask,
    LambdaResponse,
    SQSMessage,
    SQSRecord,
)
from celery_cloud.core.models.celery_task_model import CeleryTaskModel
from celery_cloud.core.exceptions import (
    EventDecodeException,
    MessageDecodeException,
    TaskDecodeException,
    BackendException,
    TaskExecutionException,
)


def call_task(celery_task: CeleryTask) -> Any:
    """Execute a Celery task and return the result

    Args:
        celery_task (CeleryTask): Celery task to execute

    Returns:
        Any: Task execution result

    """

    # TODO: allow to call remote functions

    try:
        task_result: Any = TASKS[celery_task.task](
            celery_task.args, celery_task.kwargs
        )

        logger.debug(
            f"Executed task: {celery_task.task} with ID {celery_task.id}"
        )

        return task_result

    except Exception as e:
        logger.error(f"Exception executing task {celery_task.id}: {str(e)}")

        raise TaskExecutionException(
            message=f"Exception executing task {celery_task.id}", detail=str(e)
        )


def get_event(event: dict[str, Any]) -> SQSEvent:
    """Get SQSEvent from message

    Args:
        event (dict[str, Any]): SQS event

    Returns:
        SQSEVent: Decoded event
    """

    try:
        # Validate the event with Pydantic
        sqs_event: SQSEvent = SQSEvent(**event)
        return sqs_event
    except ValidationError as e:
        logger.error(f"Invalid SQS event format: {e.json()}")
        raise EventDecodeException(
            message="Invalid SQS event format", detail=e.json()
        )
    except Exception as e:
        logger.error(f"Error decoding event: {str(e)}")
        raise EventDecodeException(
            message="Error decoding event", detail=str(e)
        )


def get_message(record: SQSRecord) -> SQSMessage:
    """Get message from SQS record

    Args:
        record (SQSRecord): _description_

    Returns:
        SQSMessage: _description_
    """

    # 3.1. Get Message from record
    try:
        message: dict[str, Any] = record.get_message()
        # TODO: validate fields exist
        sqs_message: SQSMessage = SQSMessage(
            body=message["body"],
            content_encoding=message["content-encoding"],
            content_type=message["content-type"],
            headers=message["headers"],
            properties=message["properties"],
        )

        return sqs_message

    except json.JSONDecodeError as e:
        logger.error(f"JSONDecodeError processing message: {str(e)}")

        raise MessageDecodeException(
            message="JSONDecodeError processing message", detail=str(e)
        )

    except ValidationError as e:
        logger.error(f"ValidationError processing message: {str(e)}")
        raise MessageDecodeException(
            message="ValidationError processing message", detail=str(e)
        )

    except Exception as e:
        logger.error(f"Exception processing message: {str(e)}")

        raise MessageDecodeException(
            message="Exception processing message", detail=str(e)
        )


def get_task(message: SQSMessage) -> CeleryTask:
    """Get Task from message

    Args:
        message (SQSMessage): _description_

    Returns:
        CeleryTask: _description_
    """

    # 3.1. Get Message from record
    try:
        # Create CeleryTask object
        celery_task: CeleryTask = CeleryTask(
            id=message.headers.id,
            task=message.headers.task,
            args=ast.literal_eval(
                message.headers.argsrepr
            ),  # Safely convert string to list
            kwargs=ast.literal_eval(
                message.headers.kwargsrepr
            ),  # Safely convert string to dict
        )

        return celery_task

    except json.JSONDecodeError as e:
        logger.error(f"JSONDecodeError getting task: {str(e)}")

        raise TaskDecodeException(
            message="JSONDecodeError getting task", detail=str(e)
        )

    except ValidationError as e:
        logger.error(f"ValidationError getting task: {str(e)}")
        raise TaskDecodeException(
            message="ValidationError getting task", detail=str(e)
        )

    except Exception as e:
        logger.error(f"Exception getting task: {str(e)}")

        raise TaskDecodeException(
            message="Exception getting task", detail=str(e)
        )


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda handler for processing Celery Broker events

    Args:
        event (dict[str, Any]): _description_
        context (Any): _description_

    Returns:
        dict[str, Any]: _description_
    """

    processed_tasks: list[ProcessedTask] = []
    failed_tasks: list[FailedTask] = []

    # Logging: Generate KSUID as trace_id
    trace_id = str(Ksuid())
    # Logging: Assign trace_id to context
    trace_id_context.set(trace_id)

    logger.debug(f"Processing lambda event: {event} with context: {context}")

    try:
        # 1. Decode the event depending on the event source
        # TODO: Only SQS managed by now, add more event types

        sqs_event: SQSEvent = get_event(event)

        logger.debug(f"Processing lambda event: {sqs_event.model_dump()}")

        # 3. Process the event
        for record in sqs_event.Records:
            message: dict[str, Any] = record.get_message()
            # TODO: validate fields exist
            sqs_message: SQSMessage = SQSMessage(
                body=message["body"],
                content_encoding=message["content-encoding"],
                content_type=message["content-type"],
                headers=message["headers"],
                properties=message["properties"],
            )
            logger.debug(f"Processing message: {sqs_message}")

            # 3.2. Get celery Task from message
            celery_task: CeleryTask = get_task(sqs_message)
            logger.debug(f"Processing task: {celery_task}")

            # Set task status to "PROCESSING" in backend
            CeleryTaskModel.insert_task(
                task_uuid=celery_task.id
            )

            # 3.3. Check if task is supported
            if celery_task.task not in TASKS:
                logger.error(f"Task '{celery_task.task}' not supported")

                failed_tasks.append(
                    FailedTask(
                        message_id=record.messageId,
                        task_id=celery_task.id,
                        error=f"Task '{celery_task.task}' not supported",
                    )
                )
                continue

            # 3.4. Call function with args and kwargs
            task_result: Any = call_task(celery_task)

            logger.debug(
                f"Processed task: {celery_task.task} with ID {celery_task.id}"
            )

            # 3.5. Update task status and result in backend
            CeleryTaskModel.update_task(
                celery_task.id, status="SUCCESS", result=task_result
            )

            # 3.6. Append task to processed tasks
            processed_tasks.append(
                ProcessedTask(
                    task_id=celery_task.id,
                    status="SUCCESS",
                    result=task_result,
                )
            )

        # Clear context before finishing the function
        trace_id_context.set(None)

        return LambdaResponse(
            status="completed",
            processed_messages=len(processed_tasks),
            failed_messages=len(failed_tasks),
            processed_tasks=processed_tasks if processed_tasks else None,
            failed_tasks=failed_tasks if failed_tasks else None,
        ).model_dump()

    except (
        MessageDecodeException,
        TaskDecodeException,
        BackendException,
        TaskExecutionException,
    ) as e:
        failed_tasks.append(
            FailedTask(
                message_id=record.messageId,
                error=f"{str(e)}",
            )
        )

    # TODO: Add more specific error handling (Exception) to capture all errors
    except EventDecodeException as e:
        # Clear context before finishing the function
        trace_id_context.set(None)

        return LambdaResponse(
            status="error",
            message=e.message,
            details=e.detail,
        ).model_dump()

    except Exception as e:
        # Clear context before finishing the function
        trace_id_context.set(None)

        return LambdaResponse(
            status="error",
            message=f"General error: {str(e)}",
            details=str(e),
        ).model_dump()


def lambda_runner(celery_task: CeleryTask) -> Any:
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

    # Call function with args and kwargs
    return TASKS[celery_task.task](celery_task.args, celery_task.kwargs)
