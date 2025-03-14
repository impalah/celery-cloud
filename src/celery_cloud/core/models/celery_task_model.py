import base64
import json
import datetime
from typing import Optional, Any
from pynamodb.models import Model
from pynamodb.attributes import UnicodeAttribute, BinaryAttribute, NumberAttribute


class CeleryTaskModel(Model):
    """Dynamodb model to store Celery tasks.

    Args:
        Model (_type_): _description_

    Returns:
        _type_: _description_
    """

    class Meta:
        table_name = "celery"
        region = "eu-west-1"

    # El task_id tiene un prefijo b'celery-task-meta-' antes del UUID
    task_id = UnicodeAttribute(hash_key=True)

    # El resultado se almacena en formato binario (base64)
    result = BinaryAttribute(null=True)

    # Timestamp como número flotante
    timestamp = NumberAttribute(default=lambda: datetime.datetime.now(datetime.timezone.utc).timestamp())

    @classmethod
    def insert_task(cls, task_uuid: str):
        """Insert a new task with the correct prefix.

        Args:
            task_uuid (str): _description_

        Returns:
            _type_: _description_
        """

        prefixed_task_id = f"celery-task-meta-{task_uuid}"

        task = cls(task_id=prefixed_task_id, result=None)
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
            encoded_result = base64.b64encode(json.dumps(result).encode())

            task.update(actions=[cls.result.set(encoded_result)])
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
