import bz2
import gzip
import json
import lzma
import zlib
from datetime import UTC, datetime
from decimal import Decimal

import msgpack
import pytest
import yaml

from celery_cloud import serialization
from celery_cloud.serialization import SerializationError, decompress, dumps, loads


@pytest.mark.parametrize(
    "content_type,encode",
    [
        ("application/json", lambda v: json.dumps(v).encode()),
        ("application/x-msgpack", lambda v: msgpack.packb(v, use_bin_type=True)),
        ("application/x-yaml", lambda v: yaml.safe_dump(v).encode()),
    ],
)
def test_loads_every_supported_format(content_type, encode):
    value = [[1, "two"], {"k": [3.5, None, True]}, {"callbacks": None}]
    assert loads(encode(value), content_type) == value


def test_loads_accepts_text_and_content_type_parameters():
    assert loads('{"a": 1}', "application/json; charset=utf-8") == {"a": 1}


@pytest.mark.parametrize(
    "content_type",
    ["application/x-python-serialize", "text/plain", "", "application/xml"],
)
def test_pickle_and_unknown_formats_are_refused(content_type):
    with pytest.raises(SerializationError) as raised:
        loads(b"anything", content_type)
    assert str(raised.value) == f"Unsupported content type: {content_type}"


@pytest.mark.parametrize("serializer", ["json", "msgpack", "yaml"])
def test_dumps_then_loads_round_trips(serializer):
    value = {"status": "SUCCESS", "result": [1, 2.5, "x", None], "children": []}
    content_type = serialization.SERIALIZERS[serializer]
    assert loads(dumps(value, serializer), content_type) == value


@pytest.mark.parametrize("serializer", ["json", "msgpack", "yaml"])
def test_values_the_format_cannot_hold_become_text(serializer):
    when = datetime(2025, 1, 2, 3, 4, 5, tzinfo=UTC)
    result = loads(
        dumps({"when": when, "price": Decimal("1.5"), "ids": {1, 2}}, serializer),
        serialization.SERIALIZERS[serializer],
    )
    assert result["when"] == str(when)
    assert result["price"] == "1.5"
    assert isinstance(result["ids"], str)


def test_msgpack_uses_the_binary_type_like_kombu():
    assert dumps("text", "msgpack") == msgpack.packb("text", use_bin_type=True)


def test_dumps_rejects_an_unknown_serializer():
    with pytest.raises(SerializationError, match="Unsupported serializer: pickle"):
        dumps({}, "pickle")


@pytest.mark.parametrize(
    "compression,compress",
    [
        # kombu's "gzip" is a zlib stream; a real .gz is accepted too
        ("application/x-gzip", zlib.compress),
        ("application/x-gzip", gzip.compress),
        ("application/x-bz2", bz2.compress),
        ("application/x-lzma", lzma.compress),
    ],
)
def test_decompress_every_supported_compression(compression, compress):
    assert decompress(compress(b"payload"), compression) == b"payload"


def test_no_compression_returns_the_data():
    assert decompress(b"payload", None) == b"payload"
    assert decompress(b"payload", "") == b"payload"


def test_unsupported_compression_is_refused():
    with pytest.raises(SerializationError, match="Unsupported compression: application/x-brotli"):
        decompress(b"x", "application/x-brotli")


@pytest.mark.parametrize(
    "compression", ["application/x-gzip", "application/x-bz2", "application/x-lzma"]
)
def test_corrupt_data_is_a_serialization_error(compression):
    with pytest.raises(SerializationError, match="Cannot decompress the body"):
        decompress(b"definitely not compressed", compression)


@pytest.mark.parametrize("module,extra", [("msgpack", "msgpack"), ("yaml", "yaml")])
def test_a_missing_extra_says_what_to_install(monkeypatch, module, extra):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == module:
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(SerializationError) as raised:
        dumps({"a": 1}, extra)
    assert str(raised.value) == f"{module} is not installed: pip install celery-cloud[{extra}]"
