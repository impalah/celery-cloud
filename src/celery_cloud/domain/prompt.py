from typing import Any
from celery_cloud.core.entities.test.prompt_reponse import PromptResponse
from celery_cloud.core.entities.test.prompt_request import PromptRequest
from celery_cloud.core.logging import logger


def prompt(args: list[Any], kwargs: dict[str, Any]) -> dict[str, Any]:
    """Returns a dummy response for a prompt.

    Args:
        args (list[Any]): _description_
        kwargs (dict[str, Any]): _description_

    Returns:
        dict[str, Any]: _description_
    """

    logger.debug(
        f"Executing task prompt with args: {args} and kwargs: {kwargs}"
    )

    logger.debug(
        f"Type args: {type(args)} and type kwargs: {type(kwargs)}"
    )

    # Convert the received arguments into a pydantic model
    request = PromptRequest.model_validate(args[0])

    logger.debug(f"Prompt request: {request}")

    # Create a dummy response
    response = PromptResponse(
        id="4b8f27d1-cd8b-4b79-a1d5-937c5d3579d7",
        prompt="Gimme some answers",
        response="Here you have some answers",
    )

    # Return the response as a dictionary
    return response.model_dump()
