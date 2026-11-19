import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

from celery_cloud.client import FLAGGED, REVOKED, backend_location, install, revoke

REGION = "eu-west-1"
TABLE = "results"


@pytest.fixture
def table(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    with mock_aws():
        dynamodb = boto3.client("dynamodb", region_name=REGION)
        dynamodb.create_table(
            TableName=TABLE,
            KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        yield dynamodb


def item(dynamodb, task_id):
    key = {"id": {"S": f"b'celery-task-meta-{task_id}'"}}
    return dynamodb.get_item(TableName=TABLE, Key=key, ConsistentRead=True).get("Item")


def test_revoking_a_task_that_has_not_started_writes_a_revoked_result(table):
    assert revoke("t-1", table=TABLE, region=REGION) == REVOKED

    stored = item(table, "t-1")
    meta = json.loads(stored["result"]["B"])
    assert meta["status"] == "REVOKED"
    assert meta["task_id"] == "t-1"
    assert meta["result"] == {
        "exc_type": "TaskRevokedError",
        "exc_message": ["revoked"],
        "exc_module": "celery.exceptions",
    }
    assert stored["revoked"] == {"BOOL": True}
    assert "ttl" in stored and "timestamp" in stored


def test_revoking_a_task_that_already_exists_only_flags_it(table):
    original = json.dumps({"status": "STARTED", "task_id": "t-2"}).encode()
    table.put_item(
        TableName=TABLE,
        Item={"id": {"S": "b'celery-task-meta-t-2'"}, "result": {"B": original}},
    )

    assert revoke("t-2", table=TABLE, region=REGION) == FLAGGED

    stored = item(table, "t-2")
    assert stored["result"]["B"] == original  # the state is untouched
    assert stored["revoked"] == {"BOOL": True}


def test_ttl_can_be_disabled(table):
    revoke("t-3", table=TABLE, region=REGION, ttl_seconds=0)
    assert "ttl" not in item(table, "t-3")


def test_other_dynamodb_errors_are_raised(table):
    broken = MagicMock()
    broken.put_item.side_effect = ClientError(
        {"Error": {"Code": "ProvisionedThroughputExceededException", "Message": "x"}},
        "PutItem",
    )
    with pytest.raises(ClientError):
        revoke("t-4", table=TABLE, region=REGION, client=broken)
    broken.update_item.assert_not_called()


@pytest.mark.parametrize(
    "url,expected",
    [
        ("dynamodb://@eu-central-1/my-table", ("eu-central-1", "my-table")),
        ("dynamodb://@us-east-1/t?read=5&write=5", ("us-east-1", "t")),
        ("dynamodb://@eu-west-1/my-table/", ("eu-west-1", "my-table")),
    ],
)
def test_backend_location(url, expected):
    assert backend_location(url) == expected


@pytest.mark.parametrize("url", ["redis://localhost", "dynamodb://@eu-west-1", "dynamodb:///t", ""])
def test_backend_location_rejects_other_backends(url):
    with pytest.raises(ValueError, match="Expected a result backend like"):
        backend_location(url)


def test_install_replaces_app_control_revoke(table):
    app = SimpleNamespace(
        conf=SimpleNamespace(result_backend=f"dynamodb://@{REGION}/{TABLE}"),
        control=SimpleNamespace(revoke=None),
    )
    install(app)

    app.control.revoke("t-5", terminate=True, signal="SIGKILL")
    app.control.revoke(["t-6", "t-7"])

    for task_id in ("t-5", "t-6", "t-7"):
        assert json.loads(item(table, task_id)["result"]["B"])["status"] == "REVOKED"


def test_importing_the_client_does_not_load_the_runner_settings():
    """A client application must not need the runner's configuration."""
    import subprocess
    import sys

    code = (
        "import sys, celery_cloud.client; "
        "assert 'celery_cloud.settings' not in sys.modules"
    )
    subprocess.run([sys.executable, "-I", "-c", code], check=True)  # noqa: S603


def test_the_revoked_item_has_the_exact_celery_layout(table):
    import time

    before = int(time.time())
    revoke("t-8", table=TABLE, region=REGION)
    stored = item(table, "t-8")

    assert set(stored) == {"id", "result", "timestamp", "revoked", "ttl"}
    meta = json.loads(stored["result"]["B"])
    assert set(meta) == {
        "status", "result", "traceback", "children", "date_done", "task_id",
    }
    assert meta["traceback"] is None
    assert meta["children"] == []
    assert meta["date_done"].endswith("+00:00")  # an aware UTC timestamp
    assert float(stored["timestamp"]["N"]) >= before
    # the marker expires in 24 h by default (ttl_seconds), counted from now
    assert before + 86400 <= int(stored["ttl"]["N"]) <= before + 86400 + 5


def test_a_ttl_of_one_second_is_still_written(table):
    revoke("t-9", table=TABLE, region=REGION, ttl_seconds=1)
    assert "ttl" in item(table, "t-9")


def test_the_region_of_the_table_is_used_to_create_the_client(monkeypatch):
    import celery_cloud.client as module

    created = {}
    monkeypatch.setattr(
        module.boto3,
        "client",
        lambda service, **kwargs: created.update(service=service, **kwargs) or MagicMock(),
    )
    revoke("t-10", table=TABLE, region="ap-south-1")
    assert created == {"service": "dynamodb", "region_name": "ap-south-1"}


def test_the_serializer_of_the_app_is_used_for_the_marker(table):
    import msgpack

    app = SimpleNamespace(
        conf=SimpleNamespace(
            result_backend=f"dynamodb://@{REGION}/{TABLE}", result_serializer="msgpack"
        ),
        control=SimpleNamespace(revoke=None),
    )
    install(app)
    app.control.revoke("t-11")
    meta = msgpack.unpackb(item(table, "t-11")["result"]["B"], raw=False)
    assert meta["status"] == "REVOKED"
    assert backend_location(f"dynamodb://@{REGION}/{TABLE}") == (REGION, TABLE)
