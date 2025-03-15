from celery import Celery
from time import sleep

from celery_cloud.core.celery_config import Celeryconfig


# Configure Celery
app = Celery("task_simulator")
app.config_from_object(Celeryconfig())


@app.task
def add(x: int, y: int) -> int:
    """Simple function to add two numbers. 5 seconds sleep included to simulate a long running task.

    Args:
        x (_type_): _description_
        y (_type_): _description_

    Returns:
        _type_: _description_
    """
    sleep(5)
    return x + y


@app.task
def sumar(x: int, y: int) -> int:
    """Simple function to add two numbers.

    Args:
        x (_type_): _description_
        y (_type_): _description_

    Returns:
        _type_: _description_
    """
    pass

@app.task
def restar(x: int, y: int) -> int:
    """Simple function to substract two numbers.

    Args:
        x (_type_): _description_
        y (_type_): _description_

    Returns:
        _type_: _description_
    """
    pass

