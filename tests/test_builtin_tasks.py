from unittest.mock import MagicMock, patch

import pytest

from celery_cloud.entities import Task
from celery_cloud.exceptions import TaskExecutionException
from celery_cloud.runners import builtin_tasks
from celery_cloud.runners.builtin_tasks import BUILTIN_TASKS, run_builtin


def make_task(name, kwargs):
    return Task(id="t-1", task=name, args=[], kwargs=kwargs, queue="q")


@pytest.fixture(autouse=True)
def tasks():
    with patch.object(
        builtin_tasks.settings, "TASKS", {"calc.add": "task://calc/add"}
    ):
        yield


def executor():
    mock = MagicMock()
    mock.execute.side_effect = lambda task, route: sum(task.args)
    return mock


def test_the_two_builtin_names():
    assert BUILTIN_TASKS == {"celery.map": False, "celery.starmap": True}


def test_starmap_calls_the_task_once_per_item():
    run = executor()
    spec = {"task": "calc.add", "args": [], "kwargs": {}}
    result = run_builtin(make_task("celery.starmap", {"task": spec, "it": [[1, 2], [3, 4]]}), run)

    assert result == [3, 7]
    first = run.execute.call_args_list[0].args
    assert first[0].task == "calc.add" and first[0].args == [1, 2]
    assert first[1].scheme == "task" and first[1].module == "calc"


def test_map_passes_each_item_as_the_first_argument():
    run = executor()
    spec = {"task": "calc.add", "args": [100], "kwargs": {"k": 1}}
    result = run_builtin(make_task("celery.map", {"task": spec, "it": [1, 2]}), run)

    assert result == [101, 102]
    subtask = run.execute.call_args_list[1].args[0]
    assert subtask.args == [2, 100]  # the item first, then the signature's own
    assert subtask.kwargs == {"k": 1}


def test_an_empty_iterable_gives_an_empty_list():
    spec = {"task": "calc.add"}
    assert run_builtin(make_task("celery.map", {"task": spec, "it": []}), executor()) == []


def test_a_task_that_is_not_in_tasks_is_not_run():
    spec = {"task": "other.task"}
    with pytest.raises(NotImplementedError, match="Task 'other.task' not supported"):
        run_builtin(make_task("celery.map", {"task": spec, "it": [1]}), executor())


@pytest.mark.parametrize(
    "kwargs,detail",
    [
        ({"it": [1]}, "missing the task signature"),
        ({"task": "calc.add", "it": [1]}, "missing the task signature"),
        ({"task": {"args": []}, "it": [1]}, "missing the task signature"),
        ({"task": {"task": "calc.add"}}, "missing the item list"),
        ({"task": {"task": "calc.add"}, "it": "abc"}, "missing the item list"),
    ],
)
def test_malformed_messages_are_rejected(kwargs, detail):
    with pytest.raises(TaskExecutionException) as raised:
        run_builtin(make_task("celery.map", kwargs), executor())
    assert raised.value.message == "Invalid celery.map message"
    assert raised.value.detail == detail


def test_starmap_items_must_be_lists():
    spec = {"task": "calc.add"}
    with pytest.raises(TaskExecutionException) as raised:
        run_builtin(make_task("celery.starmap", {"task": spec, "it": [5]}), executor())
    assert raised.value.detail == "item 5 is not a list of arguments"


def test_a_failing_subtask_fails_the_whole_call():
    run = MagicMock()
    run.execute.side_effect = [1, ValueError("bad item")]
    spec = {"task": "calc.add"}
    with pytest.raises(ValueError, match="bad item"):
        run_builtin(make_task("celery.map", {"task": spec, "it": [1, 2, 3]}), run)
    assert run.execute.call_count == 2  # stops at the first failure
