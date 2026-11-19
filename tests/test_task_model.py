import pytest
from unittest.mock import patch, MagicMock
import json
from celery_cloud.models.task_model import TaskModel
from celery_cloud.exceptions import BackendException


@patch("celery_cloud.models.task_model.TaskModel.save")
@patch("celery_cloud.models.task_model.settings")
def test_insert_task_success(mock_settings, mock_save):
    mock_settings.CELERY_BACKEND_TABLE = "table"
    mock_settings.CELERY_BACKEND_REGION = "region"
    mock_settings.RESULT_TTL_SECONDS = 86400
    mock_settings.RESULT_SERIALIZER = "json"

    task_uuid = "abc123"
    task = TaskModel.insert_task(task_uuid)

    assert task.id == str(f"celery-task-meta-{task_uuid}".encode())
    assert isinstance(task.result, bytes)


@patch("celery_cloud.models.task_model.TaskModel.save", side_effect=Exception("DB error"))
@patch("celery_cloud.models.task_model.settings")
def test_insert_task_error(mock_settings, mock_save):
    mock_settings.CELERY_BACKEND_TABLE = "table"
    mock_settings.CELERY_BACKEND_REGION = "region"

    with pytest.raises(BackendException) as exc:
        TaskModel.insert_task("abc123")
    assert "Error inserting task" in str(exc.value)


@patch("celery_cloud.models.task_model.TaskModel.get")
@patch("celery_cloud.models.task_model.TaskModel.update")
def test_update_task_success(mock_update, mock_get):
    mock_task = MagicMock()
    mock_get.return_value = mock_task

    task = TaskModel.update_task("abc123", "SUCCESS", result={"value": 42})
    assert task == mock_task


@patch("celery_cloud.models.task_model.TaskModel.get", side_effect=TaskModel.DoesNotExist)
def test_update_task_does_not_exist(mock_get):
    assert TaskModel.update_task("missing-id", "SUCCESS") is None


@patch("celery_cloud.models.task_model.TaskModel.get", side_effect=Exception("Boom"))
def test_update_task_error(mock_get):
    with pytest.raises(BackendException) as exc:
        TaskModel.update_task("abc123", "FAILURE")
    assert "Error updating task" in str(exc.value)


@patch("celery_cloud.models.task_model.TaskModel.get")
def test_get_task_success(mock_get):
    # what insert_task/update_task store: raw JSON bytes (no base64)
    stored = json.dumps({"status": "SUCCESS"}).encode()
    mock_task = MagicMock(result=stored, timestamp=123456.0)
    mock_get.return_value = mock_task

    task_data = TaskModel.get_task("abc123")
    assert task_data["result"]["status"] == "SUCCESS"
    assert task_data["timestamp"] == 123456.0


@patch("celery_cloud.models.task_model.TaskModel.get", side_effect=TaskModel.DoesNotExist)
def test_get_task_does_not_exist(mock_get):
    assert TaskModel.get_task("unknown") is None


@patch("celery_cloud.models.task_model.TaskModel.get", side_effect=Exception("Oops"))
def test_get_task_error(mock_get):
    with pytest.raises(BackendException) as exc:
        TaskModel.get_task("abc123")
    assert "Error getting task" in str(exc.value)


def test_get_task_reads_what_update_task_writes():
    """Regression: get_task used to base64-decode the raw JSON and always failed."""
    saved = {}

    task = MagicMock()
    task.update.side_effect = lambda actions: saved.setdefault("actions", actions)

    with patch("celery_cloud.models.task_model.TaskModel.get", return_value=task):
        TaskModel.update_task("abc123", "SUCCESS", result={"value": 42})

    from celery_cloud.models.task_model import _serialize_result
    from celery_cloud.entities import TaskResult

    stored = _serialize_result(
        TaskResult(status="SUCCESS", result={"value": 42}, task_id="abc123")
    )
    with patch(
        "celery_cloud.models.task_model.TaskModel.get",
        return_value=MagicMock(result=stored, timestamp=1.0),
    ):
        data = TaskModel.get_task("abc123")

    assert data["result"]["status"] == "SUCCESS"
    assert data["result"]["result"] == {"value": 42}


def test_task_key_matches_celery_dynamodb_backend():
    from celery_cloud.models.task_model import _task_key

    assert _task_key("abc") == "b'celery-task-meta-abc'"


def test_insert_task_uses_celery_state_started():
    with patch("celery_cloud.models.task_model.TaskModel.save"):
        task = TaskModel.insert_task("abc123")
    assert json.loads(task.result)["status"] == "STARTED"


def test_non_json_results_are_stored_as_text():
    from datetime import datetime
    from decimal import Decimal

    from celery_cloud.models.task_model import _serialize_result
    from celery_cloud.entities import TaskResult

    stored = _serialize_result(
        TaskResult(
            status="SUCCESS",
            result={"when": datetime(2025, 1, 1), "amount": Decimal("1.5")},
            task_id="x",
        )
    )
    assert json.loads(stored)["result"] == {
        "when": "2025-01-01 00:00:00",
        "amount": "1.5",
    }


def test_update_task_missing_logs_and_returns_none():
    with (
        patch(
            "celery_cloud.models.task_model.TaskModel.get",
            side_effect=TaskModel.DoesNotExist,
        ),
        patch("celery_cloud.models.task_model.logger") as logger,
    ):
        assert TaskModel.update_task("missing", "SUCCESS") is None
    logger.warning.assert_called_once()


def _put_error(code: str):
    from botocore.exceptions import ClientError
    from pynamodb.exceptions import PutError

    cause = ClientError({"Error": {"Code": code, "Message": "x"}}, "PutItem")
    # same message PynamoDB builds: it embeds the AWS error
    return PutError(f"Failed to put item: {cause}", cause)


def test_insert_task_duplicate_raises_duplicate_exception():
    from celery_cloud.exceptions import DuplicateTaskException

    with (
        patch(
            "celery_cloud.models.task_model.TaskModel.save",
            side_effect=_put_error("ConditionalCheckFailedException"),
        ),
        patch(
            "celery_cloud.models.task_model.TaskModel.get",
            return_value=MagicMock(revoked=None, attempt=0),
        ),
    ):
        with pytest.raises(DuplicateTaskException) as exc:
            TaskModel.insert_task("abc123")
    assert "already exists" in exc.value.message


def test_insert_task_other_put_error_is_backend_exception():
    """Throttling or an outage is a backend failure (retried), not a duplicate."""
    from celery_cloud.exceptions import DuplicateTaskException

    with patch(
        "celery_cloud.models.task_model.TaskModel.save",
        side_effect=_put_error("ProvisionedThroughputExceededException"),
    ):
        with pytest.raises(BackendException) as exc:
            TaskModel.insert_task("abc123")
    assert not isinstance(exc.value, DuplicateTaskException)
    assert "Error inserting task" in exc.value.message


# ---- stored format and exact error contract --------------------------------


def test_serialized_size_limit_is_inclusive():
    from celery_cloud.entities import TaskResult
    from celery_cloud.exceptions import ResultTooLargeException
    from celery_cloud.models.task_model import MAX_RESULT_BYTES, _serialize_result

    def build(padding: int) -> TaskResult:
        return TaskResult(status="SUCCESS", result="a" * padding, task_id="x")

    base = len(_serialize_result(build(0)))
    exact = _serialize_result(build(MAX_RESULT_BYTES - base))
    assert len(exact) == MAX_RESULT_BYTES  # exactly at the limit still fits

    with pytest.raises(ResultTooLargeException) as exc:
        _serialize_result(build(MAX_RESULT_BYTES - base + 1))
    assert exc.value.message == "Result of task x is too large"
    assert exc.value.detail == (
        f"{MAX_RESULT_BYTES + 1} bytes, the limit is {MAX_RESULT_BYTES} bytes"
    )


def test_insert_task_stores_complete_celery_meta():
    from datetime import UTC, datetime, timedelta

    with patch("celery_cloud.models.task_model.TaskModel.save"):
        task = TaskModel.insert_task("abc123")

    meta = json.loads(task.result)
    assert set(meta) == {
        "status", "result", "traceback", "children", "date_done", "task_id"
    }
    assert meta["status"] == "STARTED"
    assert meta["result"] is None
    assert meta["traceback"] is None
    assert meta["children"] == []
    assert meta["task_id"] == "abc123"
    done = datetime.fromisoformat(meta["date_done"])
    assert done.tzinfo is not None
    assert abs(datetime.now(UTC) - done) < timedelta(minutes=1)


def test_backend_error_contracts():
    with patch("celery_cloud.models.task_model.TaskModel.save", side_effect=Exception("DB error")):
        with pytest.raises(BackendException) as exc:
            TaskModel.insert_task("abc123")
    assert exc.value.message == "Error inserting task abc123: DB error"
    assert exc.value.detail == "DB error"

    with patch("celery_cloud.models.task_model.TaskModel.get", side_effect=Exception("Boom")):
        with pytest.raises(BackendException) as exc:
            TaskModel.update_task("abc123", "FAILURE")
        assert exc.value.message == "Error updating task abc123: Boom"
        assert exc.value.detail == "Boom"

    with patch("celery_cloud.models.task_model.TaskModel.get", side_effect=Exception("Oops")):
        with pytest.raises(BackendException) as exc:
            TaskModel.get_task("abc123")
    assert exc.value.message == "Error getting task abc123: Oops"
    assert exc.value.detail == "Oops"


def test_duplicate_and_put_error_contracts():
    from celery_cloud.exceptions import DuplicateTaskException

    with (
        patch(
            "celery_cloud.models.task_model.TaskModel.save",
            side_effect=_put_error("ConditionalCheckFailedException"),
        ),
        patch(
            "celery_cloud.models.task_model.TaskModel.get",
            return_value=MagicMock(revoked=None, attempt=0),
        ),
    ):
        with pytest.raises(DuplicateTaskException) as exc:
            TaskModel.insert_task("abc123")
    assert exc.value.message == "Task abc123 already exists"
    assert "ConditionalCheckFailedException" in exc.value.detail

    with patch(
        "celery_cloud.models.task_model.TaskModel.save",
        side_effect=_put_error("ProvisionedThroughputExceededException"),
    ):
        with pytest.raises(BackendException) as exc:
            TaskModel.insert_task("abc123")
    assert exc.value.message.startswith("Error inserting task abc123: ")
    assert "ProvisionedThroughputExceededException" in exc.value.message
    assert "ProvisionedThroughputExceededException" in exc.value.detail


def test_get_task_with_empty_result_returns_none_result():
    with patch(
        "celery_cloud.models.task_model.TaskModel.get",
        return_value=MagicMock(result=b"", timestamp=1.0),
    ):
        assert TaskModel.get_task("abc123")["result"] is None


def test_update_task_sets_timestamp_from_the_clock_in_utc():
    from datetime import UTC, datetime

    fixed = datetime(2030, 1, 2, 3, 4, 5, tzinfo=UTC)
    task = MagicMock()
    with (
        patch("celery_cloud.models.task_model.TaskModel.get", return_value=task),
        patch("celery_cloud.models.task_model.datetime") as clock,
    ):
        clock.now.return_value = fixed
        TaskModel.update_task("abc123", "SUCCESS", result=1)

    assert all(call.args == (UTC,) for call in clock.now.call_args_list)
    actions = task.update.call_args.kwargs["actions"]
    # the second action sets the timestamp attribute
    assert actions[1].values[1].values == ({"N": str(fixed.timestamp())},)


def test_update_task_missing_warning_names_the_task_and_status():
    with (
        patch(
            "celery_cloud.models.task_model.TaskModel.get",
            side_effect=TaskModel.DoesNotExist,
        ),
        patch("celery_cloud.models.task_model.logger") as logger,
    ):
        TaskModel.update_task("missing-1", "SUCCESS")
    text = logger.warning.call_args.args[0]
    assert "missing-1" in text and "SUCCESS" in text and "lost" in text


# ---- result expiration (DynamoDB TTL) ---------------------------------------



def _fixed_clock():
    from datetime import UTC, datetime

    return datetime(2030, 1, 2, 3, 4, 5, tzinfo=UTC)


def test_expires_at_is_now_plus_the_configured_seconds():
    from celery_cloud.models.task_model import _expires_at

    fixed = _fixed_clock()
    with (
        patch("celery_cloud.models.task_model.datetime") as clock,
        patch("celery_cloud.models.task_model.settings") as cfg,
    ):
        clock.now.return_value = fixed
        cfg.RESULT_TTL_SECONDS = 100
        cfg.RESULT_SERIALIZER = "json"
        assert _expires_at() == int(fixed.timestamp()) + 100
        cfg.RESULT_TTL_SECONDS = 86400
        cfg.RESULT_SERIALIZER = "json"
        assert _expires_at() == int(fixed.timestamp()) + 86400


def test_expires_at_is_none_when_disabled():
    from celery_cloud.models.task_model import _expires_at

    with patch("celery_cloud.models.task_model.settings") as cfg:
        cfg.RESULT_TTL_SECONDS = 0
        cfg.RESULT_SERIALIZER = "json"
        assert _expires_at() is None


def test_insert_task_writes_ttl_as_an_integer_epoch():
    fixed = _fixed_clock()
    with (
        patch("celery_cloud.models.task_model.TaskModel.save"),
        patch("celery_cloud.models.task_model.datetime") as clock,
        patch("celery_cloud.models.task_model.settings") as cfg,
    ):
        clock.now.return_value = fixed
        cfg.RESULT_TTL_SECONDS = 3600
        cfg.RESULT_SERIALIZER = "json"
        task = TaskModel.insert_task("abc123")

    assert task.ttl == int(fixed.timestamp()) + 3600
    assert isinstance(task.ttl, int)


def test_insert_task_omits_ttl_when_disabled():
    with (
        patch("celery_cloud.models.task_model.TaskModel.save"),
        patch("celery_cloud.models.task_model.settings") as cfg,
    ):
        cfg.RESULT_TTL_SECONDS = 0
        cfg.RESULT_SERIALIZER = "json"
        task = TaskModel.insert_task("abc123")
    assert task.ttl is None


def test_update_task_refreshes_ttl_from_the_last_state_change():
    fixed = _fixed_clock()
    task = MagicMock()
    with (
        patch("celery_cloud.models.task_model.TaskModel.get", return_value=task),
        patch("celery_cloud.models.task_model.datetime") as clock,
        patch("celery_cloud.models.task_model.settings") as cfg,
    ):
        clock.now.return_value = fixed
        cfg.RESULT_TTL_SECONDS = 600
        cfg.RESULT_SERIALIZER = "json"
        TaskModel.update_task("abc123", "SUCCESS", result=1)

    actions = task.update.call_args.kwargs["actions"]
    assert len(actions) == 3  # result, timestamp, ttl (in this order)
    assert actions[2].values[1].values == ({"N": str(int(fixed.timestamp()) + 600)},)


def test_update_task_does_not_touch_ttl_when_disabled():
    task = MagicMock()
    with (
        patch("celery_cloud.models.task_model.TaskModel.get", return_value=task),
        patch("celery_cloud.models.task_model.settings") as cfg,
    ):
        cfg.RESULT_TTL_SECONDS = 0
        cfg.RESULT_SERIALIZER = "json"
        TaskModel.update_task("abc123", "SUCCESS", result=1)

    assert len(task.update.call_args.kwargs["actions"]) == 2


def test_a_one_second_ttl_is_still_written_and_only_zero_disables():
    from celery_cloud.models.task_model import _expires_at

    fixed = _fixed_clock()
    with (
        patch("celery_cloud.models.task_model.datetime") as clock,
        patch("celery_cloud.models.task_model.settings") as cfg,
    ):
        clock.now.return_value = fixed
        cfg.RESULT_TTL_SECONDS = 1
        cfg.RESULT_SERIALIZER = "json"
        assert _expires_at() == int(fixed.timestamp()) + 1
        cfg.RESULT_TTL_SECONDS = 0
        cfg.RESULT_SERIALIZER = "json"
        assert _expires_at() is None
