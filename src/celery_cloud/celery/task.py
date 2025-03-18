from celery import Celery
from time import sleep
from typing import Any


from celery_cloud.core.celery_config import Celeryconfig
from celery_cloud.core.entities.test.prompt_reponse import PromptResponse


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


@app.task
# def prompt(prompt: PromptRequest) -> PromptResponse:
def prompt(prompt: dict[str, Any]) -> dict[str, Any]:
    """Testing complex objects serialization

    Args:
        x (int): _description_
        y (int): _description_

    Returns:
        int: _description_
    """
    pass


@app.task
def prompt2(demo: str) -> PromptResponse:
    """Testing complex objects serialization

    Args:
        x (int): _description_
        y (int): _description_

    Returns:
        int: _description_
    """
    pass
