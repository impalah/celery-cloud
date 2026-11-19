from typing import Any

from fastapi import FastAPI

from .logging import logger
from .settings import settings

app = FastAPI()

if settings.DEBUG_MODE:
    import debugpy

    # The host comes from DEBUG_HOST (loopback by default). Only expose it on
    # other interfaces (e.g. 0.0.0.0 inside a container) on trusted networks:
    # the debugger gives remote code execution to whoever can connect.
    debugpy.listen((settings.DEBUG_HOST, settings.SERVER_DEBUG_PORT))
    logger.info("Waiting for connection from the debugger...")
    debugpy.wait_for_client()


@app.post("/lambda")
async def run_lambda(event: dict[str, Any]) -> dict[str, Any]:
    from celery_cloud.runners.aws_lambda import (
        lambda_handler,
    )  # Import the real function

    return lambda_handler(event, None)
