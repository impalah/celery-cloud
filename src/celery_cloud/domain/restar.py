from typing import List, Dict
from celery_cloud.core.logging import logger


def restar(args: List[int], kwargs: Dict[str, int]) -> int:
    """Substracts all the values in args from the first one.

    Args:
        args (List[int]): _description_
        kwargs (Dict[str, int]): _description_

    Raises:
        ValueError: _description_

    Returns:
        int: _description_
    """

    logger.debug(f"Executing task restar with args: {args} and kwargs: {kwargs}")

    if len(args) < 2:
        logger.error("Needed at least 2 values to subtract")
        raise ValueError("Needed at least 2 values to subtract")
    resultado = args[0]
    for num in args[1:]:
        resultado -= num
    return resultado


