"""What happens after a task: callbacks, chains and chords.

Celery's worker does this when a task ends, from the ``embed`` part of the message
(``callbacks``, ``errbacks``, ``chain``, ``chord``). The runner does the same by
publishing the next messages to the queue:

* ``link`` callbacks receive the result as first argument.
* ``chain`` carries the remaining steps; the last element of the list is the next one.
* ``link_error`` callbacks receive the failed task id (Celery's classic errback form).
* ``chord``: every header task increments a counter in the backend when it ends; the
  one that reaches the size of the group collects the results of all the header tasks
  and sends the chord body with the list as its only argument. If any header task
  failed, the body is stored as ``FAILURE`` with a ``ChordError``.
"""

from typing import Any

from celery_cloud import messaging
from celery_cloud.entities import Task
from celery_cloud.logging import logger
from celery_cloud.messaging import QueueRef
from celery_cloud.models.canvas_model import (
    ChordCounter,
    delete_group,
    group_children,
)
from celery_cloud.models.task_model import TaskModel


def _target(signature: dict[str, Any], default: QueueRef) -> QueueRef:
    """The queue a signature goes to (``options.queue``, else the current one)."""
    name = (signature.get("options") or {}).get("queue")
    return default.named(name) if isinstance(name, str) and name else default


def _send_signature(
    signature: dict[str, Any],
    args_prefix: tuple[Any, ...],
    task: Task,
    queue: QueueRef,
    chain: list[dict[str, Any]] | None = None,
) -> str:
    target = _target(signature, queue)
    task_id, body = messaging.build_message(
        signature,
        args_prefix,
        queue=target.name,
        parent_id=task.id,
        root_id=task.root_id or task.id,
        chain=chain,
    )
    messaging.send(target, body)
    logger.debug(f"Sent {signature['task']}[{task_id}] after {task.id}")
    return task_id


def dispatch_success(task: Task, result: Any, queue: QueueRef) -> None:
    """Run what must follow a task that finished successfully."""
    for callback in task.callbacks or []:
        _send_signature(callback, (result,), task, queue)

    if task.chain:
        _send_signature(task.chain[-1], (result,), task, queue, task.chain[:-1])

    on_chord_part_return(task, queue)


def dispatch_failure(task: Task, queue: QueueRef) -> None:
    """Run what must follow a task that failed (errbacks, chord accounting)."""
    for errback in task.errbacks or []:
        _send_signature(errback, (task.id,), task, queue)

    on_chord_part_return(task, queue)


def _repr_exception(result: Any) -> str:
    """``ValueError('x')`` from the stored failure payload (for ChordError text)."""
    if isinstance(result, dict) and "exc_type" in result:
        arguments = ", ".join(repr(part) for part in result.get("exc_message") or [])
        return f"{result['exc_type']}({arguments})"
    return repr(result)


def _chord_error(chord: dict[str, Any], reason: str, queue: QueueRef) -> None:
    """The chord body cannot run: store it as FAILURE and call its errbacks."""
    options = chord.get("options") or {}
    body_id = options.get("task_id")
    logger.error(f"Chord failed: {reason}")
    if body_id:
        TaskModel.store_result(
            body_id,
            "FAILURE",
            result={
                "exc_type": "ChordError",
                "exc_message": [reason],
                "exc_module": "celery.exceptions",
            },
        )
    for errback in options.get("link_error") or []:
        failed = Task(
            id=body_id or "chord", task=chord["task"], args=[], kwargs={}
        )
        _send_signature(errback, (body_id,), failed, queue)


def on_chord_part_return(task: Task, queue: QueueRef) -> None:
    """Count a finished header task and, if it is the last one, run the chord body."""
    chord, group_id = task.chord, task.group
    if not chord or not group_id:
        return

    children = group_children(group_id)
    if children is None:
        _chord_error(chord, f"GroupResult {group_id} no longer exists", queue)
        return

    count = ChordCounter.increment(group_id)
    size = int(chord.get("chord_size") or len(children))
    if count > size:
        logger.warning(f"Chord counter incremented too many times for {group_id}")
        return
    if count < size:
        return

    # The last header task: join the results of all of them, in order
    results: list[Any] = []
    for child_id in children:
        stored = TaskModel.get_task(child_id, consistent=True)
        meta: dict[str, Any] = (stored["result"] if stored else None) or {}
        status = meta.get("status", "PENDING")
        if status in ("FAILURE", "REVOKED"):
            error = _repr_exception(meta.get("result"))
            _chord_error(chord, f"Dependency {child_id} raised {error}", queue)
            break
        if status != "SUCCESS":
            reason = f"Dependency {child_id} has no result ({status})"
            _chord_error(chord, reason, queue)
            break
        results.append(meta.get("result"))
    else:
        _send_signature(chord, (results,), task, queue)

    delete_group(group_id)
    ChordCounter.delete_for(group_id)
