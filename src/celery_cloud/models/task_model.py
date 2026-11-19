from datetime import UTC, datetime
from typing import Any

from pynamodb.attributes import (
    BinaryAttribute,
    BooleanAttribute,
    NumberAttribute,
    UnicodeAttribute,
)
from pynamodb.exceptions import PutError, UpdateError
from pynamodb.expressions.update import Action
from pynamodb.models import Model

from celery_cloud import serialization
from celery_cloud.entities import TaskResult
from celery_cloud.exceptions import (
    BackendException,
    DuplicateTaskException,
    ResultTooLargeException,
    RevokedTaskException,
)
from celery_cloud.logging import logger
from celery_cloud.settings import settings


def _task_key(task_uuid: str) -> str:
    """Build the DynamoDB hash key of a task.

    Celery's DynamoDB result backend builds the key as the *bytes* object
    ``b"celery-task-meta-<uuid>"`` and then calls ``str()`` on it, so the key
    stored in the table is literally ``b'celery-task-meta-<uuid>'`` (with the
    ``b'`` prefix and the quotes). We must produce exactly the same string for
    the Celery client to find the results written by the runner.
    """
    return str(f"celery-task-meta-{task_uuid}".encode())


def _expires_at() -> int | None:
    """Epoch second after which DynamoDB may delete the item, or None.

    Same attribute (``ttl``) and unit (epoch seconds) that Celery's own DynamoDB
    backend writes. It only has an effect when TTL is enabled on that attribute
    in the table.
    """
    seconds = settings.RESULT_TTL_SECONDS
    if seconds <= 0:
        return None
    return int(datetime.now(UTC).timestamp()) + seconds


# DynamoDB items are limited to 400 KB including attribute names; keep a margin
MAX_RESULT_BYTES = 380_000


def _serialize_result(task_result: TaskResult) -> bytes:
    """Serialize a TaskResult to the JSON bytes stored in the backend.

    Values that the serializer cannot represent (datetime, Decimal, UUID...) are
    stored as their ``str()``, so a task that already ran is never reported as failed
    just because its return value is not JSON native.

    Raises:
        ResultTooLargeException: If it does not fit in a DynamoDB item.
    """
    data = task_result.model_dump()
    # The extended keys exist only when RESULT_EXTENDED is enabled
    for key in ("name", "args", "kwargs", "worker", "retries", "queue"):
        if data.get(key) is None:
            data.pop(key, None)
    encoded = serialization.dumps(data, settings.RESULT_SERIALIZER)
    if len(encoded) > MAX_RESULT_BYTES:
        raise ResultTooLargeException(
            message=f"Result of task {task_result.task_id} is too large",
            detail=f"{len(encoded)} bytes, the limit is {MAX_RESULT_BYTES} bytes",
        )
    return encoded


class TaskModel(Model):
    """Dynamodb model to store Celery tasks.

    Args:
        Model (_type_): _description_

    Returns:
        _type_: _description_
    """

    class Meta:
        table_name = settings.CELERY_BACKEND_TABLE
        region = settings.CELERY_BACKEND_REGION

    # task_id has b'celery-task-meta-' prefix before UUID
    id = UnicodeAttribute(hash_key=True)

    # Result stored as binary attribute holding the JSON-serialized task meta
    result = BinaryAttribute(legacy_encoding=False)

    # Timestamp as floating number
    timestamp = NumberAttribute(default=lambda: datetime.now(UTC).timestamp())

    # Expiration (epoch seconds) used by the DynamoDB TTL feature; omitted when
    # RESULT_TTL_SECONDS is 0
    ttl = NumberAttribute(null=True)

    # Extra attributes, not part of Celery's layout (Celery ignores them):
    # the ``retries`` of the message that currently owns the task. A message with a
    # higher value is a retry and may take the task over; the same or a lower value
    # is a duplicate delivery.
    attempt = NumberAttribute(null=True)

    # Set by ``revoke``: the task must not run (or, if it runs, should stop)
    revoked = BooleanAttribute(null=True)

    @classmethod
    def insert_task(
        cls,
        task_uuid: str,
        meta: dict[str, Any] | None = None,
        retries: int = 0,
    ) -> "TaskModel":
        """Insert a new task with the correct prefix.

        The write is conditional: only the first delivery of a message creates
        the task, so a duplicate SQS delivery is never executed twice.

        Args:
            task_uuid (str): Celery task id.

        Raises:
            DuplicateTaskException: If the task already exists.
            BackendException: On any other backend error.
        """

        try:
            logger.debug(f"Inserting task {task_uuid}")

            task_result = TaskResult(
                status="STARTED",
                result=None,
                traceback=None,
                children=[],
                date_done=str(datetime.now(UTC).isoformat()),
                task_id=task_uuid,
                **(meta or {}),
            )

            task = cls(
                id=_task_key(task_uuid),
                result=_serialize_result(task_result),
                ttl=_expires_at(),
                # only written for retries: a first delivery keeps Celery's layout
                attempt=retries or None,
            )
            task.save(condition=cls.id.does_not_exist())

            logger.debug(f"Task {task_uuid} inserted on DynamoDB")

            return task

        except PutError as e:
            if e.cause_response_code == "ConditionalCheckFailedException":
                return cls._resolve_existing(task_uuid, retries, meta, e)
            logger.error(f"Error inserting task {task_uuid}: {str(e)}")
            raise BackendException(
                message=f"Error inserting task {task_uuid}: {str(e)}",
                detail=str(e),
            ) from e

        except Exception as e:
            logger.error(f"Error inserting task {task_uuid}: {str(e)}")
            raise BackendException(
                message=f"Error inserting task {task_uuid}: {str(e)}",
                detail=str(e),
            ) from e

    @classmethod
    def _resolve_existing(
        cls,
        task_uuid: str,
        retries: int,
        meta: dict[str, Any] | None,
        conflict: PutError,
    ) -> "TaskModel":
        """The task already exists: a duplicate, a revoked task or a retry.

        A message whose ``retries`` header is higher than the one that owns the task
        is the retry that a previous run scheduled, and takes the task over (the
        update is conditional, so two copies of it cannot both win).

        Raises:
            RevokedTaskException: The client revoked the task.
            DuplicateTaskException: The same message was delivered again.
        """
        duplicate = DuplicateTaskException(
            message=f"Task {task_uuid} already exists", detail=str(conflict)
        )
        try:
            item = cls.get(_task_key(task_uuid), consistent_read=True)
        except cls.DoesNotExist:
            raise duplicate from conflict
        except Exception as e:
            raise BackendException(
                message=f"Error reading task {task_uuid}: {str(e)}", detail=str(e)
            ) from e

        if item.revoked:
            raise RevokedTaskException(message=f"Task {task_uuid} was revoked")

        owner = int(item.attempt or 0)
        if retries <= owner:
            logger.warning(f"Task {task_uuid} already exists: duplicate delivery")
            raise duplicate from conflict

        started = TaskResult(
            status="STARTED",
            result=None,
            traceback=None,
            children=[],
            date_done=str(datetime.now(UTC).isoformat()),
            task_id=task_uuid,
            **(meta or {}),
        )
        condition = cls.attempt == owner
        if owner == 0:
            condition = condition | cls.attempt.does_not_exist()
        actions: list[Action] = [
            cls.attempt.set(retries),
            cls.result.set(_serialize_result(started)),
            cls.timestamp.set(datetime.now(UTC).timestamp()),
        ]
        expires_at = _expires_at()
        if expires_at is not None:
            actions.append(cls.ttl.set(expires_at))
        try:
            item.update(actions=actions, condition=condition)
        except UpdateError as e:
            if e.cause_response_code == "ConditionalCheckFailedException":
                raise duplicate from e
            raise BackendException(
                message=f"Error taking over task {task_uuid}: {str(e)}", detail=str(e)
            ) from e
        logger.info(f"Task {task_uuid} taken over by retry number {retries}")
        return item

    @classmethod
    def store_result(
        cls,
        task_uuid: str,
        status: str,
        result: Any | None = None,
        traceback: str | None = None,
    ) -> None:
        """Write the state of a task unconditionally (creating the item if needed).

        Used for tasks that never started, such as the body of a chord whose header
        failed.
        """
        try:
            task_result = TaskResult(
                status=status,
                result=result,
                traceback=traceback,
                children=[],
                date_done=str(datetime.now(UTC).isoformat()),
                task_id=task_uuid,
            )
            cls(
                id=_task_key(task_uuid),
                result=_serialize_result(task_result),
                ttl=_expires_at(),
            ).save()
        except Exception as e:
            raise BackendException(
                message=f"Error storing task {task_uuid}: {str(e)}", detail=str(e)
            ) from e

    @classmethod
    def delete_task(cls, task_uuid: str) -> None:
        """Remove the item of a task (so a redelivered message runs it again)."""
        try:
            cls(id=_task_key(task_uuid)).delete()
        except Exception as e:
            raise BackendException(
                message=f"Error deleting task {task_uuid}: {str(e)}", detail=str(e)
            ) from e

    @classmethod
    def is_revoked(cls, task_uuid: str) -> bool:
        """True when the client revoked the task."""
        try:
            return bool(cls.get(_task_key(task_uuid), consistent_read=True).revoked)
        except cls.DoesNotExist:
            return False
        except Exception as e:
            raise BackendException(
                message=f"Error reading task {task_uuid}: {str(e)}", detail=str(e)
            ) from e

    @classmethod
    def update_task(
        cls,
        task_uuid: str,
        status: str,
        result: Any | None = None,
        traceback: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> "TaskModel | None":
        """Update task status

        Args:
            task_uuid (str): _description_
            status (str): _description_
            result (Optional[Any], optional): Defaults to None.
            traceback (Optional[str], optional): Defaults to None.
            meta (dict, optional): Extended meta (name, args, kwargs, worker,
                retries, queue) to store with the result.

        Returns:
            _type_: _description_
        """

        logger.debug(f"Updating task {task_uuid} with status {status}")

        try:
            task = cls.get(_task_key(task_uuid))

            task_result = TaskResult(
                status=status,
                result=result,
                traceback=traceback if traceback else None,
                children=[],
                date_done=str(datetime.now(UTC).isoformat()),
                task_id=task_uuid,
                **(meta or {}),
            )

            actions: list[Action] = [
                cls.result.set(_serialize_result(task_result)),
                cls.timestamp.set(datetime.now(UTC).timestamp()),
            ]
            expires_at = _expires_at()
            if expires_at is not None:
                # the expiration counts from the last state change, like Celery
                actions.append(cls.ttl.set(expires_at))

            task.update(actions=actions)

            logger.debug(f"Task {task_uuid} updated on DynamoDB")

            return task
        except cls.DoesNotExist:
            logger.warning(
                f"Task {task_uuid} does not exist in the backend: "
                f"status {status} and result are lost"
            )
            return None
        except ResultTooLargeException:
            logger.error(f"Result of task {task_uuid} is too large for the backend")
            raise
        except Exception as e:
            logger.error(f"Error updating task {task_uuid}: {str(e)}")
            raise BackendException(
                message=f"Error updating task {task_uuid}: {str(e)}",
                detail=str(e),
            ) from e

    @classmethod
    def get_task(
        cls, task_uuid: str, consistent: bool = False
    ) -> dict[str, Any] | None:
        """Ges task status and decode result

        Args:
            task_uuid (str): _description_

        Returns:
            Optional[dict]: _description_
        """

        logger.debug(f"Getting task {task_uuid}")

        key = _task_key(task_uuid)

        try:
            task = cls.get(key, consistent_read=consistent)

            # The attribute is stored as raw JSON bytes (base64 only exists on
            # the DynamoDB wire format, PynamoDB already decodes it).
            decoded_result = (
                serialization.loads(
                    task.result, serialization.SERIALIZERS[settings.RESULT_SERIALIZER]
                )
                if task.result
                else None
            )

            logger.debug(f"Task {task_uuid} retrieved from DynamoDB")

            return {
                "task_id": key,
                "result": decoded_result,
                "timestamp": task.timestamp,
            }
        except cls.DoesNotExist:
            return None
        except Exception as e:
            logger.error(f"Error getting task {task_uuid}: {str(e)}")
            raise BackendException(
                message=f"Error getting task {task_uuid}: {str(e)}",
                detail=str(e),
            ) from e
