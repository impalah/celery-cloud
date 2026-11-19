"""Messages written with other serializers and compression (as kombu writes them)."""

import base64
import bz2
import gzip
import json
import lzma
import zlib

import msgpack
import pytest
import yaml

from celery_cloud.entities import SQSMessage, SQSRecord
from celery_cloud.exceptions import TaskDecodeException
from sqs_helpers import build_sqs_record

BODY = [[1, 2], {"k": "v"}, {"callbacks": None, "errbacks": None}]


def message(raw_body: bytes, content_type: str, compression: str | None = None):
    """A message whose body was serialized (and maybe compressed) by the client."""
    record = build_sqs_record(args=[1, 2], kwargs={"k": "v"})
    envelope = json.loads(base64.b64decode(record["body"]))
    envelope["body"] = base64.b64encode(raw_body).decode()
    envelope["content-type"] = content_type
    envelope["content-encoding"] = "binary" if compression else "utf-8"
    if compression:
        envelope["headers"]["compression"] = compression
    record["body"] = base64.b64encode(json.dumps(envelope).encode()).decode()
    return SQSMessage.from_record(SQSRecord.model_validate(record))


def check(task):
    assert task.args == [1, 2]
    assert task.kwargs == {"k": "v"}
    assert task.id == "task-1"


def test_msgpack_message():
    raw = msgpack.packb(BODY, use_bin_type=True)
    check(message(raw, "application/x-msgpack").get_task())


def test_yaml_message():
    raw = yaml.safe_dump(BODY).encode()
    check(message(raw, "application/x-yaml").get_task())


@pytest.mark.parametrize(
    "compression,compress",
    [
        ("application/x-gzip", zlib.compress),  # what kombu calls "gzip"
        ("application/x-gzip", gzip.compress),
        ("application/x-bz2", bz2.compress),
        ("application/x-lzma", lzma.compress),
    ],
)
def test_compressed_json_message(compression, compress):
    raw = compress(json.dumps(BODY).encode())
    check(message(raw, "application/json", compression).get_task())


def test_compressed_msgpack_message():
    raw = zlib.compress(msgpack.packb(BODY, use_bin_type=True))
    check(message(raw, "application/x-msgpack", "application/x-gzip").get_task())


def test_an_unsupported_compression_is_a_decode_error():
    with pytest.raises(TaskDecodeException) as raised:
        message(b"x", "application/json", "application/x-brotli").get_task()
    assert raised.value.message == "Error decoding task body"
    assert raised.value.detail == "Unsupported compression: application/x-brotli"


def test_a_corrupt_compressed_body_is_a_decode_error():
    with pytest.raises(TaskDecodeException) as raised:
        message(b"not gzip", "application/json", "application/x-gzip").get_task()
    assert raised.value.detail.startswith("Cannot decompress the body")


def test_pickle_is_refused_with_its_content_type():
    with pytest.raises(TaskDecodeException) as raised:
        message(b"\x80\x04", "application/x-python-serialize").get_task()
    assert raised.value.message == "Unsupported content type"
    assert raised.value.detail == "application/x-python-serialize"
