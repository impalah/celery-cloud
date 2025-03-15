from celery_cloud.celery.task import sumar, restar
from time import sleep

def hello() -> str:
    return "(init) Hello from celery-cloud!"


def celery() -> None:
    """Generate celery test

    Returns:
        str: _description_
    """

    print("Starting celery client")
    result = sumar.apply_async((10, 5)) #, countdown=10)
    print(f"Task ID: {result.id}")

    while not result.ready():
        print(f"Task not ready yet: {result.state}")
        sleep(1)

    print(f"Task ID finished. Result: {result.get()}")

