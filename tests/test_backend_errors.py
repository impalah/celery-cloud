"""Error paths of the backend models: every failure becomes a BackendException."""

from unittest.mock import MagicMock, patch

import pytest
from pynamodb.exceptions import UpdateError

from celery_cloud.exceptions import (
    BackendException,
    DuplicateTaskException,
    RevokedTaskException,
)
from celery_cloud.models import canvas_model
from celery_cloud.models.canvas_model import ChordCounter, delete_group, group_children
from celery_cloud.models.task_model import TaskModel
from celery_cloud.runners import canvas


class FailingConflict(Exception):
    cause_response_code = "ConditionalCheckFailedException"


# -- canvas items ------------------------------------------------------------------


def test_increment_failure_is_a_backend_exception():
    with patch.object(ChordCounter, "update", side_effect=RuntimeError("throttled")):
        with pytest.raises(BackendException) as raised:
            ChordCounter.increment("g-1")
    assert raised.value.message == (
        "Error counting the chord of group g-1: throttled"
    )
    assert raised.value.detail == "throttled"


def test_deleting_the_counter_can_fail():
    with patch.object(ChordCounter, "delete", side_effect=RuntimeError("denied")):
        with pytest.raises(BackendException) as raised:
            ChordCounter.delete_for("g-1")
    assert raised.value.message == "Error deleting the chord of group g-1: denied"


def test_reading_a_group_can_fail():
    with patch.object(TaskModel, "get", side_effect=RuntimeError("timeout")):
        with pytest.raises(BackendException) as raised:
            group_children("g-1")
    assert raised.value.message == "Error reading group g-1: timeout"


def test_deleting_a_group_can_fail():
    with patch.object(TaskModel, "delete", side_effect=RuntimeError("denied")):
        with pytest.raises(BackendException) as raised:
            delete_group("g-1")
    assert raised.value.message == "Error deleting group g-1: denied"


def test_the_keys_match_the_ones_of_celery():
    assert canvas_model._group_key("abc") == "b'celery-taskset-meta-abc'"
    assert canvas_model._chord_key("abc") == "b'chord-unlock-abc'"


def test_a_failure_payload_that_is_not_a_dict_is_shown_with_repr():
    assert canvas._repr_exception("plain text") == "'plain text'"
    assert canvas._repr_exception(None) == "None"
    assert canvas._repr_exception({"exc_type": "X", "exc_message": []}) == "X()"


# -- task model ----------------------------------------------------------------------


def test_storing_a_result_can_fail():
    with patch.object(TaskModel, "save", side_effect=RuntimeError("full")):
        with pytest.raises(BackendException) as raised:
            TaskModel.store_result("t-1", "FAILURE", {"a": 1})
    assert raised.value.message == "Error storing task t-1: full"


def test_deleting_a_task_can_fail():
    with patch.object(TaskModel, "delete", side_effect=RuntimeError("denied")):
        with pytest.raises(BackendException) as raised:
            TaskModel.delete_task("t-1")
    assert raised.value.message == "Error deleting task t-1: denied"


def test_is_revoked_of_an_unknown_task_is_false():
    with patch.object(TaskModel, "get", side_effect=TaskModel.DoesNotExist()):
        assert TaskModel.is_revoked("t-1") is False


def test_is_revoked_reads_the_flag():
    with patch.object(TaskModel, "get", return_value=MagicMock(revoked=True)):
        assert TaskModel.is_revoked("t-1") is True
    with patch.object(TaskModel, "get", return_value=MagicMock(revoked=None)):
        assert TaskModel.is_revoked("t-1") is False


def test_is_revoked_failure_is_a_backend_exception():
    with patch.object(TaskModel, "get", side_effect=RuntimeError("down")):
        with pytest.raises(BackendException) as raised:
            TaskModel.is_revoked("t-1")
    assert raised.value.message == "Error reading task t-1: down"


def conflict():
    return FailingConflict("conflict")


def test_a_conflict_whose_item_vanished_is_a_duplicate():
    with patch.object(TaskModel, "get", side_effect=TaskModel.DoesNotExist()):
        with pytest.raises(DuplicateTaskException):
            TaskModel._resolve_existing("t-1", 0, None, conflict())


def test_a_conflict_that_cannot_be_read_is_a_backend_exception():
    with patch.object(TaskModel, "get", side_effect=RuntimeError("down")):
        with pytest.raises(BackendException) as raised:
            TaskModel._resolve_existing("t-1", 0, None, conflict())
    assert raised.value.message == "Error reading task t-1: down"


def test_a_revoked_task_is_reported_as_such():
    with patch.object(TaskModel, "get", return_value=MagicMock(revoked=True, attempt=0)):
        with pytest.raises(RevokedTaskException):
            TaskModel._resolve_existing("t-1", 5, None, conflict())


def item(attempt):
    mock = MagicMock(revoked=None, attempt=attempt)
    return mock


def test_a_failing_take_over_update_is_a_backend_exception():
    owner = item(0)
    owner.update.side_effect = UpdateError("boom", RuntimeError("throttled"))
    with patch.object(TaskModel, "get", return_value=owner):
        with pytest.raises(BackendException) as raised:
            TaskModel._resolve_existing("t-1", 1, None, conflict())
    assert raised.value.message.startswith("Error taking over task t-1: ")


def test_a_lost_take_over_race_is_a_duplicate():
    cause = RuntimeError("cond")
    cause.response = {"Error": {"Code": "ConditionalCheckFailedException"}}  # type: ignore[attr-defined]
    owner = item(1)
    error = UpdateError("conditional failed", cause)
    owner.update.side_effect = error
    with patch.object(TaskModel, "get", return_value=owner):
        with patch.object(UpdateError, "cause_response_code", "ConditionalCheckFailedException", create=True):
            with pytest.raises(DuplicateTaskException):
                TaskModel._resolve_existing("t-1", 2, None, conflict())


def test_taking_over_without_ttl_does_not_write_the_ttl():
    owner = item(1)
    with patch.object(TaskModel, "get", return_value=owner):
        with patch("celery_cloud.models.task_model.settings") as cfg:
            cfg.RESULT_TTL_SECONDS = 0
            cfg.RESULT_SERIALIZER = "json"
            TaskModel._resolve_existing("t-1", 2, None, conflict())
    actions = owner.update.call_args.kwargs["actions"]
    assert len(actions) == 3  # attempt, result, timestamp: no ttl
