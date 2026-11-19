from datetime import UTC, datetime, timedelta

import pytest

from celery_cloud.entities import Task

NOW = datetime(2025, 6, 1, 12, 0, tzinfo=UTC)


def make_task(expires=None) -> Task:
    return Task(id="t", task="a.b", args=[], kwargs={}, expires=expires)


def test_no_expires_never_expires():
    assert make_task().is_expired(NOW) is False


@pytest.mark.parametrize(
    "expires,expected",
    [
        ("2025-06-01T11:59:59+00:00", True),  # past
        ("2025-06-01T12:00:00+00:00", True),  # exactly now counts as expired
        ("2025-06-01T12:00:01+00:00", False),  # future
        ("2025-06-01T14:00:00+02:00", True),  # other timezone, equals 12:00 UTC
        ("2025-06-01T13:59:59+02:00", True),
        ("2025-06-01T14:00:01+02:00", False),
    ],
)
def test_timezone_aware_expires(expires, expected):
    assert make_task(expires).is_expired(NOW) is expected


@pytest.mark.parametrize(
    "expires,expected",
    [("2025-06-01T11:00:00", True), ("2025-06-01T13:00:00", False)],
)
def test_naive_expires_is_assumed_utc(expires, expected):
    assert make_task(expires).is_expired(NOW) is expected


@pytest.mark.parametrize("expires", ["tomorrow", "2025-13-45", "12345abc"])
def test_malformed_expires_does_not_expire(expires):
    """A broken header must not make the runner discard the task."""
    assert make_task(expires).is_expired(NOW) is False


def test_uses_current_time_by_default():
    assert make_task((datetime.now(UTC) - timedelta(seconds=5)).isoformat()).is_expired()
    assert not make_task((datetime.now(UTC) + timedelta(hours=1)).isoformat()).is_expired()
