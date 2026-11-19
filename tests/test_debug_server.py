import asyncio
from unittest.mock import patch

from celery_cloud import debug_server


def test_debug_server_does_not_start_debugger_by_default():
    assert debug_server.settings.DEBUG_MODE is False
    assert debug_server.settings.DEBUG_HOST == "127.0.0.1"


def test_run_lambda_endpoint_delegates_to_handler():
    with patch(
        "celery_cloud.runners.aws_lambda.lambda_handler", return_value={"ok": True}
    ) as handler:
        result = asyncio.run(debug_server.run_lambda({"Records": []}))

    assert result == {"ok": True}
    handler.assert_called_once_with({"Records": []}, None)
