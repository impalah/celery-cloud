from typing import List, Dict
from celery_cloud.core.logging import logger


def sumar(args: List[int], kwargs: Dict[str, int]) -> int:
    """Adds all the values in args.

    Args:
        args (List[int]): _description_
        kwargs (Dict[str, int]): _description_

    Returns:
        int: _description_
    """

    logger.debug(f"Executing task sumar with args: {args} and kwargs: {kwargs}")
    return sum(args)

