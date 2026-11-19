import pytest
from celery_cloud.exceptions.runner_base_exception import RunnerBaseException


def test_runner_base_exception_str_and_repr():
    exc = RunnerBaseException(message="Error occurred", detail="Something went wrong")

    assert isinstance(exc, RunnerBaseException)
    assert str(exc) == "Error occurred: Something went wrong"
    assert repr(exc) == "RunnerBaseException(message=Error occurred, detail='Something went wrong')"


def test_runner_base_exception_without_detail():
    exc = RunnerBaseException(message="Just a message")

    assert isinstance(exc, RunnerBaseException)
    assert str(exc) == "Just a message"
    assert repr(exc) == "RunnerBaseException(message=Just a message, detail=None)"


def test_runner_base_exception_args_and_pickle():
    import pickle

    exc = RunnerBaseException(message="m", detail="d")

    assert exc.args == ("m", "d")
    clone = pickle.loads(pickle.dumps(exc))
    assert (clone.message, clone.detail) == ("m", "d")
