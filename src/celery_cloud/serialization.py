"""Serializers and compression of Celery messages and results.

JSON is built in. MessagePack and YAML need an extra
(``pip install celery-cloud[msgpack]`` / ``celery-cloud[yaml]``). ``pickle`` is **not**
supported on purpose: unpickling a message from a queue executes arbitrary code.
"""

import bz2
import json
import lzma
import zlib
from collections.abc import Callable
from typing import Any

JSON = "application/json"
MSGPACK = "application/x-msgpack"
YAML = "application/x-yaml"

# ``result_serializer`` names (and the content types of messages) the runner understands
SERIALIZERS = {"json": JSON, "msgpack": MSGPACK, "yaml": YAML}
CONTENT_TYPES = {value: name for name, value in SERIALIZERS.items()}

def _inflate(data: bytes) -> bytes:
    """zlib or gzip data (``wbits`` 47 detects the header of either).

    kombu names its zlib compression ``application/x-gzip`` (aliases ``gzip`` and
    ``zlib``): what a Celery client sends with ``task_compression="gzip"`` is a zlib
    stream, not a ``.gz`` file. Both are accepted.
    """
    return zlib.decompress(data, zlib.MAX_WBITS | 32)


# ``compression`` header values written by kombu (brotli and zstd need extra libraries
# and are not supported)
_DECOMPRESSORS: dict[str, Callable[[bytes], bytes]] = {
    "application/x-gzip": _inflate,
    "application/x-bz2": bz2.decompress,
    "application/x-lzma": lzma.decompress,
}


class SerializationError(Exception):
    """The data cannot be decoded or encoded with the requested format."""


def _optional(module: str, extra: str) -> Any:
    try:
        return __import__(module)
    except ImportError as e:
        raise SerializationError(
            f"{module} is not installed: pip install celery-cloud[{extra}]"
        ) from e


def decompress(data: bytes, compression: str | None) -> bytes:
    """Undo the ``compression`` of a message body (gzip/zlib, bzip2 and lzma)."""
    if not compression:
        return data
    try:
        decompressor = _DECOMPRESSORS[compression]
    except KeyError:
        raise SerializationError(f"Unsupported compression: {compression}") from None
    try:
        return decompressor(data)
    except (OSError, ValueError, zlib.error, lzma.LZMAError) as e:
        raise SerializationError(f"Cannot decompress the body: {e}") from e


def loads(data: bytes | str, content_type: str) -> Any:
    """Decode ``data`` written with the serializer of ``content_type``."""
    kind = CONTENT_TYPES.get(content_type.split(";")[0].strip())
    if kind is None:
        raise SerializationError(f"Unsupported content type: {content_type}")
    raw = data.encode() if isinstance(data, str) else data
    if kind == "json":
        return json.loads(raw)
    if kind == "msgpack":
        return _optional("msgpack", "msgpack").unpackb(raw, raw=False)
    return _optional("yaml", "yaml").safe_load(raw)


def dumps(value: Any, serializer: str = "json") -> bytes:
    """Encode ``value`` with ``serializer`` (``json``, ``msgpack`` or ``yaml``).

    Values the format cannot hold (datetime, Decimal, UUID...) are stored as their
    ``str()``, so a task that ran is never reported as failed over its return value.
    """
    if serializer not in SERIALIZERS:
        raise SerializationError(f"Unsupported serializer: {serializer}")
    plain = json.loads(json.dumps(value, default=str))
    if serializer == "json":
        return json.dumps(plain).encode()
    if serializer == "msgpack":
        packed: bytes = _optional("msgpack", "msgpack").packb(plain, use_bin_type=True)
        return packed
    dumped: str = _optional("yaml", "yaml").safe_dump(plain)
    return dumped.encode()
