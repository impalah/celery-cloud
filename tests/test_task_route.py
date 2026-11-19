from celery_cloud.entities import (
    TaskRoute,
)


def test_parse_task_url_basic():
    url = "task://my_module/my_function"
    route = TaskRoute.from_url(url)
    assert route.scheme == "task"
    assert route.module == "my_module"
    assert route.function == "my_function"
    assert route.query == {}


def test_parse_task_url_with_query():
    url = "task://my_mod/my_func?x=1&y=2"
    route = TaskRoute.from_url(url)
    assert route.query == {"x": ["1"], "y": ["2"]}


def test_unsupported_scheme_error_contract():
    import pytest

    from celery_cloud.entities import Task
    from celery_cloud.exceptions import TaskExecutionException
    from celery_cloud.runners.task_executor import TaskExecutor

    route = TaskRoute.from_url("ftp://host/path")
    with pytest.raises(TaskExecutionException) as exc:
        TaskExecutor().execute(Task(id="a", task="t", args=[], kwargs={}), route)
    assert exc.value.message == "Unsupported task scheme: ftp"
    assert exc.value.detail == "ftp"
