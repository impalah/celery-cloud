from celery_cloud.celery.task import sumar, restar, prompt, prompt2

from time import sleep
from celery_cloud.core.entities.test.prompt_reponse import PromptResponse
from celery_cloud.core.entities.test.prompt_request import PromptRequest


def hello() -> str:
    return "(init) Hello from celery-cloud!"


def celery() -> None:
    """Generate celery test

    Returns:
        str: _description_
    """

    print("Starting celery client")

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
