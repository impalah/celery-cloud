import sys
import types

import pytest

from celery_cloud.entities import Task, TaskRoute
from celery_cloud.exceptions import TaskExecutionException
from celery_cloud.runners.local_strategy import LocalTaskExecutionStrategy


@pytest.fixture
def fake_module():
    module = types.ModuleType("fake_local_tasks")
    module.add = lambda args, kwargs: sum(args) + kwargs.get("extra", 0)  # type: ignore[attr-defined]
    sys.modules["fake_local_tasks"] = module
    yield module
    del sys.modules["fake_local_tasks"]


def route(module: str, function: str) -> TaskRoute:
    return TaskRoute(scheme="task", module=module, function=function, query={})


def test_success_calls_function_with_args_and_kwargs(fake_module):
    task = Task(id="abc", task="t", args=[1, 2], kwargs={"extra": 10})

    result = LocalTaskExecutionStrategy().execute(task, route("fake_local_tasks", "add"))

    assert result == 13


def test_missing_function_raises_attribute_error(fake_module):
    task = Task(id="abc", task="t", args=[], kwargs={})
    with pytest.raises(AttributeError):
        LocalTaskExecutionStrategy().execute(task, route("fake_local_tasks", "nope"))


def test_missing_module_raises_import_error():
    task = Task(id="abc", task="t", args=[], kwargs={})
    with pytest.raises(ModuleNotFoundError):
        LocalTaskExecutionStrategy().execute(task, route("no_such_module_xyz", "f"))


@pytest.mark.parametrize("module,function", [("fake_local_tasks", ""), ("", "add")])
def test_incomplete_route_is_rejected(module, function):
    task = Task(id="abc", task="t", args=[], kwargs={})
    with pytest.raises(TaskExecutionException) as exc:
        LocalTaskExecutionStrategy().execute(task, route(module, function))
    assert exc.value.message == "Invalid local route for task t"
    assert exc.value.detail == "expected task://<module>/<function>"


def test_a_decorated_task_sees_the_whole_request():
    """Every field of the message reaches ``self.request`` (mutation-tested)."""
    import sys
    import types

    from celery_cloud import task
    from celery_cloud.entities import Task, TaskRoute
    from celery_cloud.runners.local_strategy import LocalTaskExecutionStrategy

    seen = {}

    @task(bind=True)
    def probe(self, a, b=0):
        seen.update(vars(self.request))
        return a + b

    module = types.ModuleType("probe_module")
    module.probe = probe
    sys.modules["probe_module"] = module
    callbacks = [{"task": "cb"}]
    chord = {"task": "body"}
    task_entity = Task(
        id="t-1", task="my.task", args=[1], kwargs={"b": 2}, retries=4,
        eta="2030-01-01T00:00:00+00:00", expires="2031-01-01T00:00:00+00:00",
        parent_id="p-1", root_id="r-1", group="g-1", group_index=3, queue="the-queue",
        callbacks=callbacks, errbacks=[{"task": "eb"}], chain=[{"task": "ch"}],
        chord=chord, time_limit=60, soft_time_limit=30,
    )
    try:
        result = LocalTaskExecutionStrategy().execute(
            task_entity, TaskRoute("task", "probe_module", "probe", {})
        )
    finally:
        del sys.modules["probe_module"]

    assert result == 3
    assert seen["id"] == "t-1" and seen["task"] == "my.task"
    assert seen["args"] == [1] and seen["kwargs"] == {"b": 2}
    assert seen["retries"] == 4
    assert seen["eta"] == "2030-01-01T00:00:00+00:00"
    assert seen["expires"] == "2031-01-01T00:00:00+00:00"
    assert (seen["parent_id"], seen["root_id"]) == ("p-1", "r-1")
    assert (seen["group"], seen["group_index"]) == ("g-1", 3)
    assert seen["delivery_info"] == {"routing_key": "the-queue"}
    assert seen["callbacks"] == callbacks
    assert seen["errbacks"] == [{"task": "eb"}]
    assert seen["chain"] == [{"task": "ch"}]
    assert seen["chord"] == chord
    assert (seen["time_limit"], seen["soft_time_limit"]) == (60, 30)
    assert seen["hostname"] == "celery-cloud"


def test_the_hostname_is_the_lambda_function_name(monkeypatch):
    import sys
    import types

    from celery_cloud import task
    from celery_cloud.entities import Task, TaskRoute
    from celery_cloud.runners.local_strategy import LocalTaskExecutionStrategy

    seen = []

    @task(bind=True)
    def probe(self):
        seen.append(self.request.hostname)

    module = types.ModuleType("probe_module2")
    module.probe = probe
    sys.modules["probe_module2"] = module
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "my-runner")
    try:
        LocalTaskExecutionStrategy().execute(
            Task(id="t", task="x", args=[], kwargs={}),
            TaskRoute("task", "probe_module2", "probe", {}),
        )
    finally:
        del sys.modules["probe_module2"]
    assert seen == ["my-runner"]


def test_task_options_of_routes_that_are_not_local():
    from celery_cloud.entities import TaskRoute
    from celery_cloud.runners.local_strategy import task_options

    assert task_options(TaskRoute("lambda", "arn", "", {})) is None
    assert task_options(TaskRoute("task", "", "fn", {})) is None
    assert task_options(TaskRoute("task", "mod", "", {})) is None
