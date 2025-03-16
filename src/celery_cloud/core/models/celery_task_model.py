import base64
import json
from datetime import datetime, timezone
from typing import Optional, Any
from pynamodb.models import Model
from pynamodb.attributes import UnicodeAttribute, BinaryAttribute, NumberAttribute
from celery_cloud.core.entities import CeleryTaskResult



class CeleryTaskModel(Model):
    """Dynamodb model to store Celery tasks.

    Args:
        Model (_type_): _description_

    Returns:
        _type_: _description_
    """

    class Meta:
        # TODO: send to settings
        table_name = "celery"
        region = "eu-west-1"

    # task_id has b'celery-task-meta-' prefix before UUID
    id = UnicodeAttribute(hash_key=True)

    # Result stored as binary (base64)
    result = BinaryAttribute(legacy_encoding=False)

    # Timestamp as floating number
    timestamp = NumberAttribute(default=lambda: datetime.now(timezone.utc).timestamp())

    @classmethod
    def insert_task(cls, task_uuid: str) -> "CeleryTaskModel":
        """Insert a new task with the correct prefix.

        Args:
            task_uuid (str): _description_

        Returns:
            _type_: _description_
        """

        prefixed_task_id = f"celery-task-meta-{task_uuid}"

        task_result = CeleryTaskResult(
            status="PROCESSING",
            result=None,
            traceback=None,
            children=[],
            date_done=str(datetime.now(timezone.utc).isoformat()),
            task_id=task_uuid,
        )

        # encoded_result = base64.b64encode(json.dumps(task_result.model_dump()).encode())
        encoded_result = json.dumps(task_result.model_dump()).encode()


        task = cls(id=prefixed_task_id, result=encoded_result)
        task.save()
        return task

    @classmethod
    def update_task(cls, task_uuid: str, status: str, result: Optional[Any] = None, traceback: Optional[str] = None):
        """Update task status

        Args:
            task_uuid (str): _description_
            status (str): _description_
            result (Optional[Any], optional): _description_. Defaults to None.
            traceback (Optional[str], optional): _description_. Defaults to None.

        Returns:
            _type_: _description_
        """
        

        prefixed_task_id = f"celery-task-meta-{task_uuid}"

        try:
            task = cls.get(prefixed_task_id)


            task_result = CeleryTaskResult(
                status=status,
                result=result,
                traceback=traceback if traceback else None,
                children=[],
                date_done=str(datetime.now(timezone.utc).isoformat()),
                task_id=task_uuid,
            )

            # encoded_result = base64.b64encode(json.dumps(task_result.model_dump()).encode())
            encoded_result = json.dumps(task_result.model_dump()).encode()

            task.update(actions=[cls.result.set(encoded_result), cls.timestamp.set(datetime.now(timezone.utc).timestamp())])
            return task
        except cls.DoesNotExist:
            return None

    @classmethod
    def get_task(cls, task_uuid: str) -> Optional[dict]:
        """Ges task status and decode result

        Args:
            task_uuid (str): _description_

        Returns:
            Optional[dict]: _description_
        """

        prefixed_task_id = f"celery-task-meta-{task_uuid}"

        try:
            task = cls.get(prefixed_task_id)

            decoded_result = (
                json.loads(base64.b64decode(task.result).decode()) if task.result else None
            )

            return {
                "task_id": task.task_id,
                "result": decoded_result,
                "timestamp": task.timestamp,
            }
        except cls.DoesNotExist:
            return None
