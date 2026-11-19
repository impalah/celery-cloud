"""Results written with msgpack/yaml are what a client with that result_serializer reads."""

import sys
import types
from unittest.mock import patch

import msgpack
import pytest
import yaml

from celery_cloud.models.task_model import TaskModel, _task_key
from celery_cloud.runners import aws_lambda
from celery_cloud.runners.aws_lambda import lambda_handler
from sqs_helpers import build_sqs_record


@pytest.fixture
def add_task():
    module = types.ModuleType("ser_tasks")
    module.add = lambda args, kwargs: sum(args)
    module.boom = lambda args, kwargs: 1 / 0
    sys.modules["ser_tasks"] = module
    routes = {"t.add": "task://ser_tasks/add", "t.boom": "task://ser_tasks/boom"}
    with patch.object(aws_lambda.settings, "TASKS", routes):
        yield
    del sys.modules["ser_tasks"]


def raw_result(task_id):
    return TaskModel.get(_task_key(task_id), consistent_read=True).result


@pytest.mark.parametrize(
    "serializer,decode",
    [
        ("msgpack", lambda raw: msgpack.unpackb(raw, raw=False)),
        ("yaml", lambda raw: yaml.safe_load(raw)),
    ],
)
def test_the_result_is_stored_with_the_configured_serializer(
    aws, add_task, monkeypatch, serializer, decode
):
    monkeypatch.setattr(aws_lambda.settings, "RESULT_SERIALIZER", serializer)
    monkeypatch.setattr("celery_cloud.models.task_model.settings.RESULT_SERIALIZER", serializer)

    lambda_handler({"Records": [build_sqs_record("t.add", "s1", args=[2, 3])]}, None)

    meta = decode(raw_result("s1"))
    assert meta["status"] == "SUCCESS"
    assert meta["result"] == 5
    assert TaskModel.get_task("s1")["result"]["result"] == 5  # and the runner reads it


def test_failures_use_the_configured_serializer_too(aws, add_task, monkeypatch):
    monkeypatch.setattr("celery_cloud.models.task_model.settings.RESULT_SERIALIZER", "msgpack")

    lambda_handler({"Records": [build_sqs_record("t.boom", "s2")]}, None)

    meta = msgpack.unpackb(raw_result("s2"), raw=False)
    assert meta["status"] == "FAILURE"
    assert meta["result"]["exc_type"] == "ZeroDivisionError"


def test_json_is_the_default(aws, add_task):
    import json

    lambda_handler({"Records": [build_sqs_record("t.add", "s3", args=[1])]}, None)
    assert json.loads(raw_result("s3"))["result"] == 1
