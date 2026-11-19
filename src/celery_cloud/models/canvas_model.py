"""Backend items that Celery uses to run groups and chords.

Celery's DynamoDB backend keeps two kinds of items next to the task results, in the
same table and with the same ``id`` hash key:

* ``b'celery-taskset-meta-<group id>'``: written by the client when it starts a chord,
  it lists the ids of the header tasks (``result`` holds the JSON of the group result).
* ``b'chord-unlock-<group id>'``: a counter (``chord_count``) that every header task
  increments when it finishes; the one that reaches the size of the group runs the
  chord body.

The runner reads and updates them exactly as Celery's worker does.
"""

from datetime import UTC, datetime
from typing import Any

from pynamodb.attributes import NumberAttribute, UnicodeAttribute
from pynamodb.models import Model

from celery_cloud import serialization
from celery_cloud.exceptions import BackendException
from celery_cloud.models.task_model import TaskModel
from celery_cloud.settings import settings


def _group_key(group_id: str) -> str:
    return str(f"celery-taskset-meta-{group_id}".encode())


def _chord_key(group_id: str) -> str:
    return str(f"chord-unlock-{group_id}".encode())


class ChordCounter(Model):
    """The counter item of a chord (``chord_count``, as in Celery's backend)."""

    class Meta:
        table_name = settings.CELERY_BACKEND_TABLE
        region = settings.CELERY_BACKEND_REGION

    id = UnicodeAttribute(hash_key=True)
    chord_count = NumberAttribute(null=True)
    timestamp = NumberAttribute(null=True)

    @classmethod
    def increment(cls, group_id: str) -> int:
        """Atomically add one to the counter and return the new value."""
        try:
            counter = cls(id=_chord_key(group_id))
            counter.update(
                actions=[
                    cls.chord_count.add(1),
                    cls.timestamp.set(datetime.now(UTC).timestamp()),
                ]
            )
            return int(counter.chord_count)
        except Exception as e:
            raise BackendException(
                message=f"Error counting the chord of group {group_id}: {str(e)}",
                detail=str(e),
            ) from e

    @classmethod
    def delete_for(cls, group_id: str) -> None:
        try:
            cls(id=_chord_key(group_id)).delete()
        except Exception as e:
            raise BackendException(
                message=f"Error deleting the chord of group {group_id}: {str(e)}",
                detail=str(e),
            ) from e


def group_children(group_id: str) -> list[str] | None:
    """Ids of the tasks of a group, in order (None when the group does not exist)."""
    try:
        item = TaskModel.get(_group_key(group_id), consistent_read=True)
    except TaskModel.DoesNotExist:
        return None
    except Exception as e:
        raise BackendException(
            message=f"Error reading group {group_id}: {str(e)}", detail=str(e)
        ) from e

    # {"result": [[group id, parent], [[[task id, parent], parent], ...]]}
    parsed: dict[str, Any] = serialization.loads(
        item.result, serialization.SERIALIZERS[settings.RESULT_SERIALIZER]
    )
    children = parsed["result"][1]
    return [str(child[0][0]) for child in children]


def delete_group(group_id: str) -> None:
    """Remove the group item once the chord is finished."""
    try:
        TaskModel(id=_group_key(group_id)).delete()
    except Exception as e:
        raise BackendException(
            message=f"Error deleting group {group_id}: {str(e)}", detail=str(e)
        ) from e
