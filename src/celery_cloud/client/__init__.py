from celery_cloud.celery.task import prompt

from time import sleep
from celery_cloud.core.entities.test.prompt_request import PromptRequest
from celery import current_app


def hello() -> str:
    return "(init) Hello from celery-cloud!"


def celery() -> None:
    """Generate celery test

    Returns:
        str: _description_
    """

    print("Starting celery client")

    # Print backend configuration
    app = current_app._get_current_object()
    print("-" * 40)

    print(f"Broker URL: {app.conf.broker_url}")
    print(f"Result Backend URL: {app.conf.result_backend}")
    print(
        f"Result Backend Transport Options: "
        f"{app.conf.result_backend_transport_options}"
    )
    print(f"Broker Transport Options: {app.conf.broker_transport_options}")
    print(f"Task Default Queue: {app.conf.task_default_queue}")
    print(
        f"Broker Connection Retry On Startup: "
        f"{app.conf.broker_connection_retry_on_startup}"
    )
    print(f"Task Create Missing Queues: {app.conf.task_create_missing_queues}")

    print("-" * 40)

    request = PromptRequest(
        id="4b8f27d1-cd8b-4b79-a1d5-937c5d3579d7", prompt="Gimme some answers"
    )

    result = prompt.apply_async(
        args=(request.model_dump(),)
    )  # , countdown=10)
    # result = sumar.apply_async((10, 5)) #, countdown=10)
    print(f"Task ID: {result.id}")

    while not result.ready():
        print(f"Task not ready yet: {result.state}")
        sleep(1)

    print(f"Task ID finished. Result: {result.get()}")
