import json
import logging
from unittest.mock import patch

import pytest

from celery_cloud import metrics, signals
from celery_cloud.signals import Signal


# -- signals --------------------------------------------------------------------


def test_receivers_get_the_keyword_arguments():
    signal = Signal("demo")
    seen = []
    signal.connect(lambda **kwargs: seen.append(kwargs))
    signal.send(task_id="t-1", extra=2)
    assert seen == [{"task_id": "t-1", "extra": 2}]


def test_connect_works_as_a_decorator_and_returns_the_function():
    signal = Signal("demo")

    @signal.connect
    def receiver(**kwargs):
        return "x"

    assert receiver() == "x"
    assert receiver in signal._receivers


def test_connecting_twice_registers_once():
    signal = Signal("demo")
    seen = []

    def receiver(**kwargs):
        seen.append(1)

    signal.connect(receiver)
    signal.connect(receiver)
    signal.send()
    assert seen == [1]


def test_disconnect_removes_the_receiver_and_ignores_unknown_ones():
    signal = Signal("demo")
    seen = []

    def receiver(**kwargs):
        seen.append(1)

    signal.connect(receiver)
    signal.disconnect(receiver)
    signal.disconnect(receiver)  # not connected any more: no error
    signal.send()
    assert seen == []


def test_a_failing_receiver_is_logged_and_the_others_still_run(caplog):
    signal = Signal("demo")
    seen = []

    def broken(**kwargs):
        raise RuntimeError("receiver bug")

    signal.connect(broken)
    signal.connect(lambda **kwargs: seen.append("second"))

    with caplog.at_level(logging.ERROR, logger="celery_cloud.signals"):
        signal.send()

    assert seen == ["second"]
    assert "Receiver" in caplog.text and "demo" in caplog.text


def test_a_receiver_can_disconnect_itself_while_the_signal_is_sent():
    signal = Signal("demo")
    seen = []

    def once(**kwargs):
        seen.append("once")
        signal.disconnect(once)

    signal.connect(once)
    signal.connect(lambda **kwargs: seen.append("other"))
    signal.send()
    signal.send()
    assert seen == ["once", "other", "other"]


def test_the_standard_signals_exist():
    for name in ("task_prerun", "task_postrun", "task_success", "task_failure", "task_retry"):
        assert getattr(signals, name).name == name


# -- metrics --------------------------------------------------------------------


@pytest.fixture
def enabled():
    with patch.object(metrics.settings, "METRICS_ENABLED", True):
        with patch.object(metrics.settings, "METRICS_NAMESPACE", "TestApp"):
            yield


def test_nothing_is_written_when_metrics_are_disabled(capsys):
    metrics.emit("t.add", "TaskSucceeded", 0.5)
    assert capsys.readouterr().out == ""


def test_an_outcome_is_one_emf_line(enabled, capsys):
    metrics.emit("t.add", "TaskSucceeded", 0.25)

    line = json.loads(capsys.readouterr().out)
    assert line["Task"] == "t.add"
    assert line["TaskSucceeded"] == 1
    assert line["TaskDuration"] == 250.0
    declaration = line["_aws"]["CloudWatchMetrics"][0]
    assert declaration["Namespace"] == "TestApp"
    assert declaration["Dimensions"] == [["Task"]]
    assert declaration["Metrics"] == [
        {"Name": "TaskSucceeded", "Unit": "Count"},
        {"Name": "TaskDuration", "Unit": "Milliseconds"},
    ]
    assert isinstance(line["_aws"]["Timestamp"], int)


def test_an_outcome_without_a_run_has_no_duration(enabled, capsys):
    metrics.emit("t.add", "TaskSkipped")

    line = json.loads(capsys.readouterr().out)
    assert "TaskDuration" not in line
    assert line["_aws"]["CloudWatchMetrics"][0]["Metrics"] == [
        {"Name": "TaskSkipped", "Unit": "Count"}
    ]
