def add(args: list, kwargs: dict) -> int:
    return sum(args) + kwargs.get("extra", 0)


def boom(args: list, kwargs: dict) -> None:
    raise ValueError("this task always fails")
