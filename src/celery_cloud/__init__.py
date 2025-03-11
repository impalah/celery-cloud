from celery_cloud.task import add
from time import sleep

def hello() -> str:
    return "(init) Hello from celery-cloud!"


def celery() -> None:
    """Generate celery test

    Returns:
        str: _description_
    """

    print("Starting celery client")
    result = add.apply_async((3, 2)) #, countdown=10)
    print(f"Task ID: {result.id}")

    while not result.ready():
        print("Task not ready yet...")
        sleep(1)

    print(f"Task ID finished. Result: {result.get()}")

