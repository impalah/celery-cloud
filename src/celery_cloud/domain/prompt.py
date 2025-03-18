from typing import List, Dict, Any
from celery_cloud.core.entities.test.prompt_reponse import PromptResponse
from celery_cloud.core.logging import logger



def prompt(args: List[int], kwargs: Dict[str, int]) -> Dict[str, Any]:
    """Returns a dummy response for a prompt.

    Args:
        args (List[int]): _description_
        kwargs (Dict[str, int]): _description_

    Returns:
        int: _description_
    """

    logger.debug(f"Executing task prompt with args: {args} and kwargs: {kwargs}")

    response = PromptResponse(id="4b8f27d1-cd8b-4b79-a1d5-937c5d3579d7", prompt="Gimme some answers", response="Here you have some answers")

    return response.model_dump()

