from .runner_base_exception import (
    RunnerBaseException,
)


class BackendException(RunnerBaseException):
    """Domain exception for backend errors"""

    ...


class EventDecodeException(RunnerBaseException):
    """Domain exception for message decoding errors"""

    ...


class MessageDecodeException(RunnerBaseException):
    """Domain exception for message decoding errors"""

    ...


class TaskDecodeException(RunnerBaseException):
    """Domain exception for task decoding errors"""

    ...


class TaskExecutionException(RunnerBaseException):
    """Domain exception for execution exceptions"""

    ...


class DuplicateTaskException(RunnerBaseException):
    """Domain exception: the task already exists in the backend.

    SQS delivers messages at least once, so this is the expected way a
    duplicate delivery shows up. It must not be executed again.
    """

    ...


class ResultTooLargeException(RunnerBaseException):
    """Domain exception: the task result does not fit in a backend item.

    Retrying cannot help, so it is stored as a task failure instead of being
    treated as a backend outage.
    """

    ...


class RevokedTaskException(RunnerBaseException):
    """Domain exception: the task was revoked before it started."""

    ...
