from typing import Any

import pytest

from sqs_helpers import build_sqs_record


@pytest.fixture
def sqs_record():
    return build_sqs_record


@pytest.fixture
def sqs_event():
    def _build(*records: dict[str, Any]) -> dict[str, Any]:
        return {"Records": list(records)}

    return _build
