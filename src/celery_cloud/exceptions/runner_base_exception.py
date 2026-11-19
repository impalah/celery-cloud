class RunnerBaseException(Exception):
    """Base Domain exception for runner errors

    Args:
        message (str): Human readable description of the error.
        detail (str | None): Extra information (original error, payload...).
    """

    def __init__(self, message: str, detail: str | None = None) -> None:
        super().__init__(message, detail)
        self.message = message
        self.detail = detail

    def __str__(self) -> str:
        if self.detail is None:
            return self.message
        return f"{self.message}: {self.detail}"

    def __repr__(self) -> str:
        class_name = self.__class__.__name__
        return f"{class_name}(message={self.message}, detail={self.detail!r})"
