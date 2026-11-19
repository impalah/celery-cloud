import threading
import time

import pytest

from celery_cloud.deadline import (
    effective_limits,
    remaining_seconds,
    signals_available,
    time_limits,
)
from celery_cloud.exceptions import SoftTimeLimitExceeded, TimeLimitExceeded


class FakeContext:
    def __init__(self, millis):
        self.millis = millis

    def get_remaining_time_in_millis(self):
        return self.millis


def test_remaining_seconds_from_a_lambda_context():
    assert remaining_seconds(FakeContext(12_500)) == 12.5


@pytest.mark.parametrize("context", [None, object(), FakeContext("soon"), FakeContext(True)])
def test_remaining_seconds_is_unknown_without_a_usable_context(context):
    assert remaining_seconds(context) is None


def test_remaining_seconds_survives_a_failing_context():
    class Broken:
        def get_remaining_time_in_millis(self):
            raise RuntimeError("boom")

    assert remaining_seconds(Broken()) is None


def test_soft_limit_interrupts_the_running_code():
    with pytest.raises(SoftTimeLimitExceeded) as exc, time_limits(0.05, None):
        time.sleep(2)
    assert str(exc.value) == "SoftTimeLimitExceeded(0.05,)"


def test_hard_limit_interrupts_the_running_code():
    with pytest.raises(TimeLimitExceeded) as exc, time_limits(None, 0.05):
        time.sleep(2)
    assert str(exc.value) == "TimeLimitExceeded(0.05,)"


def test_integer_limits_are_formatted_like_celery():
    with pytest.raises(SoftTimeLimitExceeded) as exc, time_limits(1, None):
        time.sleep(3)
    assert str(exc.value) == "SoftTimeLimitExceeded(1,)"


def test_hard_reason_replaces_the_default_message():
    with pytest.raises(TimeLimitExceeded, match="close to the timeout"), time_limits(
        None, 0.05, "close to the timeout"
    ):
        time.sleep(2)


def test_the_task_can_catch_the_soft_limit_and_the_hard_limit_still_applies():
    caught = []
    with pytest.raises(TimeLimitExceeded), time_limits(0.05, 0.2):
        try:
            time.sleep(2)
        except SoftTimeLimitExceeded:
            caught.append("soft")  # clean up...
            time.sleep(2)  # ...but keeps running

    assert caught == ["soft"]


def test_a_task_that_finishes_in_time_is_not_interrupted():
    with time_limits(5, 10):
        assert sum(range(10)) == 45


def test_the_timer_and_the_signal_handler_are_restored():
    import signal

    before = signal.getsignal(signal.SIGALRM)
    with time_limits(5, 10):
        assert signal.getsignal(signal.SIGALRM) is not before
        assert signal.getitimer(signal.ITIMER_REAL)[0] > 0
    assert signal.getsignal(signal.SIGALRM) is before
    assert signal.getitimer(signal.ITIMER_REAL)[0] == 0


@pytest.mark.parametrize("soft,hard", [(None, None), (0, 0), (-1, -5)])
def test_no_timer_without_a_positive_limit(soft, hard):
    import signal

    with time_limits(soft, hard):
        assert signal.getitimer(signal.ITIMER_REAL)[0] == 0


def test_limits_are_not_enforced_outside_the_main_thread():
    outcome = []

    def work():
        assert signals_available() is False
        with time_limits(0.01, 0.02):
            time.sleep(0.15)
        outcome.append("finished")

    thread = threading.Thread(target=work)
    thread.start()
    thread.join()
    assert outcome == ["finished"]


def test_effective_limits_without_a_lambda_context():
    assert effective_limits(3, 9, None, 10) == (3, 9, None)


def test_effective_limits_use_the_task_hard_limit_when_it_is_shorter():
    assert effective_limits(None, 5, 300, 10) == (None, 5, None)


def test_effective_limits_use_the_lambda_budget_when_it_is_shorter():
    soft, hard, reason = effective_limits(2, 500, 40, 10)
    assert (soft, hard) == (2, 30)
    assert reason == (
        "The Lambda function is about to reach its timeout (stopped after 30 s)"
    )


def test_effective_limits_set_a_hard_limit_from_the_lambda_when_the_task_has_none():
    assert effective_limits(None, None, 25, 10)[1] == 15


def test_effective_limits_never_return_a_non_positive_budget():
    assert effective_limits(None, None, 5, 10)[1] == 0.001
