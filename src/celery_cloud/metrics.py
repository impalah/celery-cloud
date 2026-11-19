"""CloudWatch metrics through the Embedded Metric Format (EMF).

When ``METRICS_ENABLED=true`` the runner writes one JSON line per task outcome to its
log; CloudWatch turns it into metrics without any API call (and no extra permission).
Metrics, with the task name as dimension: ``TaskSucceeded``, ``TaskFailed``,
``TaskRetried``, ``TaskSkipped`` (duplicate, expired, revoked), ``TaskDelayed`` (held
until the eta), ``TaskIgnored`` / ``TaskRejected``, and ``TaskDuration`` in
milliseconds for the tasks that ran.
"""

import json
import sys
import time

from celery_cloud.settings import settings


def emit(task_name: str, outcome: str, duration_seconds: float | None = None) -> None:
    """Write the EMF line of one task outcome (``outcome`` is the metric name)."""
    if not settings.METRICS_ENABLED:
        return
    metrics = [{"Name": outcome, "Unit": "Count"}]
    values: dict[str, float] = {outcome: 1}
    if duration_seconds is not None:
        metrics.append({"Name": "TaskDuration", "Unit": "Milliseconds"})
        values["TaskDuration"] = round(duration_seconds * 1000, 3)
    line = {
        "_aws": {
            "Timestamp": int(time.time() * 1000),
            "CloudWatchMetrics": [
                {
                    "Namespace": settings.METRICS_NAMESPACE,
                    "Dimensions": [["Task"]],
                    "Metrics": metrics,
                }
            ],
        },
        "Task": task_name,
        **values,
    }
    sys.stdout.write(json.dumps(line) + "\n")
    sys.stdout.flush()
