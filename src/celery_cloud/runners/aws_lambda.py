import builtins
import contextvars
import importlib
import json
import math
import os
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from ksuid import Ksuid

from celery_cloud import metrics, signals
from celery_cloud.deadline import effective_limits, remaining_seconds, time_limits
from celery_cloud.entities import (
    BatchItemFailure,
    DelayedTask,
    FailedTask,
    LambdaResponse,
    ProcessedTask,
    SkippedTask,
    SQSEvent,
    SQSMessage,
    SQSRecord,
    Task,
    TaskRoute,
)
from celery_cloud.exceptions import (
    BackendException,
    DuplicateTaskException,
    EventDecodeException,
    Ignore,
    MessageDecodeException,
    Reject,
    Retry,
    RevokedTaskException,
    RunnerBaseException,
    TaskDecodeException,
    TaskExecutionException,
)
from celery_cloud.logging import logger, trace_id_context
from celery_cloud.messaging import QueueRef, delay_message, retry_message, send
from celery_cloud.models.task_model import TaskModel
from celery_cloud.runtime import reset_runtime, set_runtime
from celery_cloud.settings import settings

from . import canvas
from .builtin_tasks import BUILTIN_TASKS, run_builtin
from .lambda_strategy import LambdaFunctionError
from .local_strategy import task_options
from .task_executor import TaskExecutor

# Names kept importable from this module (public API used by callers and tests)
__all__ = [
    "BackendException",
    "EventDecodeException",
    "MessageDecodeException",
    "TaskDecodeException",
    "TaskExecutionException",
    "TaskRoute",
    "call_task",
    "lambda_handler",
]


def call_task(task: Task, seconds_left: float | None = None) -> Any:
    """Execute a Celery task and return the result.

    Args:
        task: The task to run.
        seconds_left: Seconds before AWS stops the invocation (None = unknown).
            The task is stopped before that, with the time limits of the message.
    """
    try:
        executor = TaskExecutor()
        route = (
            None
            if task.task in BUILTIN_TASKS
            else TaskRoute.from_url(settings.TASKS[task.task])
        )

        # The limits of the message win; the ones of @task(...) are the default
        soft, hard = task.soft_time_limit, task.time_limit
        options = task_options(route) if route is not None else None
        if options is not None:
            soft = soft if soft is not None else options.soft_time_limit
            hard = hard if hard is not None else options.time_limit
        soft, hard, reason = effective_limits(
            soft, hard, seconds_left, settings.TIMEOUT_MARGIN_SECONDS
        )
        with time_limits(soft, hard, reason):
            if route is None:
                task_result = run_builtin(task, executor)
            else:
                task_result = executor.execute(task, route)

        logger.debug(f"Executed task: {task.task} with ID {task.id}")
        return task_result

    except (Retry, Ignore, Reject):
        # Control flow of the task, not errors: the runner handles them
        raise

    except TaskExecutionException as e:
        # Already a domain error with its own message: do not hide it.
        logger.error(f"Exception executing task {task.id}: {e}")
        raise TaskExecutionException(
            message=f"Exception executing task {task.id}",
            detail=f"{e.message}: {e.detail}" if e.detail else e.message,
        ) from e

    except Exception as e:
        logger.error(f"Exception executing task {task.id}: {str(e)}")
        raise TaskExecutionException(
            message=f"Exception executing task {task.id}", detail=str(e)
        ) from e


def _original_error(error: BaseException) -> BaseException:
    """The error raised by the task itself, under the runner's wrappers."""
    for _ in range(10):
        if isinstance(error, TaskExecutionException) and error.__cause__ is not None:
            error = error.__cause__
        else:
            break
    return error


def _json_args(error: BaseException) -> list[Any]:
    """``error.args`` as JSON values (Celery rebuilds ``cls(*exc_message)``)."""
    if isinstance(error, RunnerBaseException):
        # (message, detail) is an implementation detail: the text is what matters
        return [str(error)]
    args: list[Any] = []
    for arg in error.args:
        try:
            json.dumps(arg)
            args.append(arg)
        except (TypeError, ValueError):
            args.append(str(arg))
    if not args and str(error):
        args.append(str(error))
    return args


def _lambda_error_payload(error: LambdaFunctionError) -> dict[str, Any]:
    """Failure of a remote function, from the error document Lambda returns."""
    try:
        document = json.loads(error.detail or "")
    except ValueError:
        document = {}
    if not isinstance(document, dict):
        document = {}
    name = str(document.get("errorType") or "LambdaFunctionError")
    candidate = getattr(builtins, name, None)
    is_builtin = isinstance(candidate, type) and issubclass(candidate, BaseException)
    return {
        "exc_type": name,
        "exc_message": [str(document.get("errorMessage") or error.message)],
        "exc_module": "builtins" if is_builtin else "remote_lambda",
    }


def _failure_payload(error: BaseException) -> dict[str, Any]:
    """Build the ``result`` Celery expects for a task in FAILURE state.

    It describes the **original** exception, so the client can do
    ``except ValueError``: Celery rebuilds the class from ``exc_module`` and
    ``exc_type`` (or creates one with that name if it cannot import it).
    """
    error = _original_error(error)
    if isinstance(error, LambdaFunctionError):
        return _lambda_error_payload(error)
    return {
        "exc_type": type(error).__name__,
        "exc_message": _json_args(error),
        "exc_module": getattr(type(error), "celery_module", type(error).__module__),
    }


def _extended_meta(record: SQSRecord, task: Task) -> dict[str, Any] | None:
    """Extra meta Celery's ``result_extended`` reads (opt-in: args may be secret)."""
    if not settings.RESULT_EXTENDED:
        return None
    return {
        "name": task.task,
        "args": task.args,
        "kwargs": task.kwargs,
        "worker": os.getenv("AWS_LAMBDA_FUNCTION_NAME", "celery-cloud"),
        "retries": task.retries or 0,
        "queue": record.eventSourceARN.rsplit(":", 1)[-1],
    }


def _revoked_payload(task: Task) -> dict[str, Any]:
    """Build the ``result`` Celery expects for a REVOKED (expired) task."""
    return {
        "exc_type": "TaskRevokedError",
        "exc_message": [f"expired at {task.expires}"],
        "exc_module": "celery.exceptions",
    }


def _queue(record: SQSRecord) -> QueueRef:
    return QueueRef.from_arn(record.eventSourceARN)


def _meta_kwargs(meta: dict[str, Any] | None) -> dict[str, Any]:
    """``meta`` keyword for the backend calls, only when there is extended meta."""
    return {"meta": meta} if meta else {}


def _record_failure(
    task: Task, error: BaseException, meta: dict[str, Any] | None = None
) -> None:
    """Store the FAILURE state of a task, never raising.

    The original error is what matters: if the backend is also down we only
    log it, so the caller can still report the task as failed. Nothing is
    stored for tasks sent with ``ignore_result``.
    """
    if task.ignore_result:
        return

    try:
        TaskModel.update_task(
            task.id,
            status="FAILURE",
            result=_failure_payload(error),
            traceback="".join(
                traceback.format_exception(type(error), error, error.__traceback__)
            ),
            **_meta_kwargs(meta),
        )
    except Exception as backend_error:
        logger.error(
            f"Could not store FAILURE state of task {task.id}: {backend_error}"
        )


def _guarded(action: str, task: Task, call: Any) -> None:
    """Run a follow-up step (callbacks, chord...) without ever raising.

    The task itself already has its final state; a problem sending the next messages
    is logged, it must not turn a finished task into a failed one.
    """
    try:
        call()
    except Exception as e:
        logger.error(f"Could not {action} for task {task.id}: {e}")


def _fail_task(
    record: SQSRecord,
    task: Task,
    error: BaseException,
    meta: dict[str, Any] | None,
) -> None:
    """Store the failure and run the errbacks and the chord accounting."""
    signals.task_failure.send(
        task_id=task.id,
        task=task.task,
        exception=_original_error(error),
        traceback="".join(
            traceback.format_exception(type(error), error, error.__traceback__)
        ),
    )
    _record_failure(task, error, meta)
    _guarded(
        "run the error callbacks",
        task,
        lambda: canvas.dispatch_failure(task, _queue(record)),
    )


class _Runtime:
    """What the running task can reach: custom states and revocation."""

    def __init__(self, task: Task, meta: dict[str, Any] | None) -> None:
        self._task = task
        self._meta = meta

    def update_state(self, task_id: str, state: str, meta: object) -> None:
        if self._task.ignore_result:
            return
        TaskModel.update_task(
            task_id, status=state, result=meta, **_meta_kwargs(self._meta)
        )

    def is_revoked(self, task_id: str) -> bool:
        return TaskModel.is_revoked(task_id)


@dataclass(frozen=True)
class _Outcome:
    """Result of processing one record."""

    result: ProcessedTask | FailedTask | SkippedTask | DelayedTask
    # True when SQS must deliver the message again (backend failure)
    retry: bool = False


def _delay_until_eta(record: SQSRecord, task: Task) -> _Outcome | None:
    """Hold a task whose ``eta`` is still in the future.

    SQS can delay a message at most 15 minutes, so the message is sent back to the
    queue with the largest delay that does not overshoot, as many times as needed
    until the ``eta`` arrives. The task is not registered meanwhile (the client sees
    it as pending, as with a Celery worker that has not reached it yet).
    """
    remaining = task.eta_seconds()
    if remaining is None or remaining < 1:
        return None
    delay = delay_message(record, remaining)
    logger.info(f"Task {task.id} holds until {task.eta}: delayed {delay} s")
    return _Outcome(
        DelayedTask(message_id=record.messageId, task_id=task.id, delay_seconds=delay)
    )


def _register_task(
    record: SQSRecord, task: Task, meta: dict[str, Any] | None = None
) -> "_Outcome | None":
    """Store the STARTED state and decide whether the task must be skipped.

    The write is conditional: a duplicate delivery of the same message is not
    executed again, while the message of a retry takes the task over. Nothing is
    stored for tasks sent with ``ignore_result``.

    Returns:
        An ``_Outcome`` with a SkippedTask when the task must not run, None
        when it can be executed.
    """
    if not task.ignore_result:
        extra: dict[str, Any] = _meta_kwargs(meta)
        if task.retries:
            extra["retries"] = task.retries
        try:
            TaskModel.insert_task(task_uuid=task.id, **extra)
        except DuplicateTaskException:
            logger.warning(f"Task {task.id} already received, skipping")
            return _Outcome(
                SkippedTask(
                    message_id=record.messageId,
                    task_id=task.id,
                    reason="duplicate message: the task already exists",
                )
            )
        except RevokedTaskException:
            logger.warning(f"Task {task.id} was revoked, skipping")
            return _Outcome(
                SkippedTask(
                    message_id=record.messageId,
                    task_id=task.id,
                    reason="task revoked",
                )
            )

    # A task received after its expiration time is not run
    if task.is_expired():
        logger.warning(f"Task {task.id} expired at {task.expires}, skipping")
        if not task.ignore_result:
            TaskModel.update_task(
                task.id,
                status="REVOKED",
                result=_revoked_payload(task),
                **_meta_kwargs(meta),
            )
        return _Outcome(
            SkippedTask(
                message_id=record.messageId,
                task_id=task.id,
                reason=f"task expired at {task.expires}",
            )
        )

    return None


def _retry_countdown(retry: Retry) -> tuple[datetime, float]:
    """When the next attempt runs, and how many seconds from now."""
    now = datetime.now(UTC)
    if retry.eta is not None:
        eta = retry.eta if retry.eta.tzinfo else retry.eta.replace(tzinfo=UTC)
    else:
        eta = now + timedelta(seconds=retry.countdown or 0)
    return eta, max((eta - now).total_seconds(), 0.0)


def _handle_retry(
    record: SQSRecord, task: Task, retry: Retry, meta: dict[str, Any] | None
) -> _Outcome:
    """Schedule another attempt: the same message with ``retries + 1`` and an eta."""
    eta, wait = _retry_countdown(retry)
    next_retries = (task.retries or 0) + 1
    try:
        send(
            _queue(record),
            retry_message(record, next_retries, eta),
            delay_seconds=math.ceil(wait),
        )
    except Exception as e:
        logger.error(f"Could not schedule the retry of task {task.id}: {e}")
        _fail_task(record, task, retry.exc or e, meta)
        return _Outcome(
            FailedTask(
                message_id=record.messageId,
                task_id=task.id,
                error=f"Could not schedule the retry: {e}",
            )
        )

    if not task.ignore_result:
        reason = retry.exc or retry
        TaskModel.update_task(
            task.id,
            status="RETRY",
            result=_failure_payload(reason),
            traceback="".join(
                traceback.format_exception(type(reason), reason, reason.__traceback__)
            ),
            **_meta_kwargs(meta),
        )
    logger.info(f"Task {task.id} will run again (retry {next_retries}) at {eta}")
    return _Outcome(ProcessedTask(task_id=task.id, status="RETRY", result=None))


def _handle_reject(
    record: SQSRecord, task: Task, reject: Reject, meta: dict[str, Any] | None
) -> _Outcome:
    """The task rejected its message: give it back to SQS, or drop it."""
    if reject.requeue:
        # forget the task so the redelivered message runs it again
        if not task.ignore_result:
            TaskModel.delete_task(task.id)
        return _Outcome(
            FailedTask(
                message_id=record.messageId,
                task_id=task.id,
                error=f"Rejected, requeued: {reject.reason}",
            ),
            retry=True,
        )
    if not task.ignore_result:
        TaskModel.update_task(
            task.id,
            status="REJECTED",
            result=reject.reason,
            **_meta_kwargs(meta),
        )
    return _Outcome(ProcessedTask(task_id=task.id, status="REJECTED", result=None))


def _postrun(task: Task, state: str, retval: Any = None) -> None:
    signals.task_postrun.send(
        task_id=task.id,
        task=task.task,
        args=task.args,
        kwargs=task.kwargs,
        retval=retval,
        state=state,
    )


def _run_task(
    record: SQSRecord,
    task: Task,
    meta: dict[str, Any] | None,
    deadline: float | None,
) -> _Outcome:
    """Execute the task and store how it ended."""
    seconds_left = None if deadline is None else deadline - time.monotonic()
    started = time.perf_counter()
    token = set_runtime(_Runtime(task, meta))
    try:
        signals.task_prerun.send(
            task_id=task.id, task=task.task, args=task.args, kwargs=task.kwargs
        )
        task_result: Any = call_task(task, seconds_left)
    except Ignore:
        logger.info(f"Task {task.id} ignored its result")
        _postrun(task, "IGNORED")
        return _Outcome(ProcessedTask(task_id=task.id, status="IGNORED", result=None))
    except Reject as reject:
        _postrun(task, "REJECTED")
        return _handle_reject(record, task, reject, meta)
    except Retry as retry:
        signals.task_retry.send(
            task_id=task.id, task=task.task, reason=retry.exc or retry, eta=retry.eta
        )
        _postrun(task, "RETRY")
        return _handle_retry(record, task, retry, meta)
    except Exception:
        _postrun(task, "FAILURE")
        raise
    finally:
        _run_info()["duration"] = time.perf_counter() - started
        reset_runtime(token)

    if not task.ignore_result:
        TaskModel.update_task(
            task.id, status="SUCCESS", result=task_result, **_meta_kwargs(meta)
        )
    signals.task_success.send(task_id=task.id, task=task.task, result=task_result)
    _postrun(task, "SUCCESS", task_result)
    _guarded(
        "run the callbacks",
        task,
        lambda: canvas.dispatch_success(task, task_result, _queue(record)),
    )
    return _Outcome(
        ProcessedTask(task_id=task.id, status="SUCCESS", result=task_result)
    )


# Per-record scratch data for the metrics (task name, how long it ran)
_info: ContextVar[dict[str, Any] | None] = ContextVar("celery_cloud_info", default=None)


def _run_info() -> dict[str, Any]:
    info = _info.get()
    return info if info is not None else {}


_OUTCOME_METRICS = {
    "SUCCESS": "TaskSucceeded",
    "RETRY": "TaskRetried",
    "IGNORED": "TaskIgnored",
    "REJECTED": "TaskRejected",
}


def _emit_metric(outcome: _Outcome, info: dict[str, Any]) -> None:
    result = outcome.result
    if isinstance(result, ProcessedTask):
        name = _OUTCOME_METRICS.get(result.status, "TaskSucceeded")
    elif isinstance(result, FailedTask):
        name = "TaskFailed"
    elif isinstance(result, SkippedTask):
        name = "TaskSkipped"
    else:
        name = "TaskDelayed"
    metrics.emit(info["task"], name, info["duration"])


def _process_record(record: SQSRecord, deadline: float | None = None) -> _Outcome:
    """Process one SQS record and report metrics. It never raises."""
    info: dict[str, Any] = {"task": "unknown", "duration": None}
    token = _info.set(info)
    try:
        outcome = _process_record_inner(record, deadline)
    finally:
        _info.reset(token)
    _guarded_metric(outcome, info)
    return outcome


def _guarded_metric(outcome: _Outcome, info: dict[str, Any]) -> None:
    try:
        _emit_metric(outcome, info)
    except Exception as e:  # metrics must never break the processing
        logger.error(f"Could not write the metrics: {e}")


def _process_record_inner(
    record: SQSRecord, deadline: float | None = None
) -> _Outcome:
    """Process one SQS record. It never raises.

    A failing record must not prevent the rest of the batch from being
    processed, and must not be silently lost.

    Args:
        record: The SQS record.
        deadline: ``time.monotonic()`` value at which AWS stops the invocation
            (None when unknown).
    """
    task: Task | None = None
    meta: dict[str, Any] | None = None

    # Not enough time left to run anything: hand the message back to SQS
    if deadline is not None and (
        deadline - time.monotonic() <= settings.TIMEOUT_MARGIN_SECONDS
    ):
        logger.warning(
            f"Not starting message {record.messageId}: the Lambda timeout is close"
        )
        return _Outcome(
            FailedTask(
                message_id=record.messageId,
                task_id=None,
                error="Not started: the Lambda function is about to time out",
            ),
            retry=True,
        )

    try:
        # 1. Decode message and task
        sqs_message = SQSMessage.from_record(record)
        logger.debug(f"Processing message {record.messageId}")

        task = sqs_message.get_task()
        _run_info()["task"] = task.task
        logger.debug(f"Processing task: {task.task} with ID {task.id}")
        meta = _extended_meta(record, task)

        # 2. A task with a future eta is held back, not run
        delayed = _delay_until_eta(record, task)
        if delayed is not None:
            return delayed

        # 3. Register the task; duplicates, revoked and expired tasks are not run
        skipped = _register_task(record, task, meta)
        if skipped is not None:
            return skipped

        # 4. Check if task is supported
        if task.task not in settings.TASKS and task.task not in BUILTIN_TASKS:
            logger.error(f"Task '{task.task}' not supported")
            error = NotImplementedError(f"Task '{task.task}' not supported")
            _fail_task(record, task, error, meta)
            return _Outcome(
                FailedTask(
                    message_id=record.messageId,
                    task_id=task.id,
                    error=f"Task '{task.task}' not supported",
                )
            )

        # 5. Run it and store the outcome
        return _run_task(record, task, meta, deadline)

    except BackendException as e:
        # The state could not be stored: report it so the message is retried
        logger.error(f"Backend error processing message {record.messageId}: {e}")
        return _Outcome(
            FailedTask(
                message_id=record.messageId,
                task_id=task.id if task else None,
                error=str(e),
            ),
            retry=True,
        )

    except RunnerBaseException as e:
        logger.error(f"Error processing message {record.messageId}: {e}")
        if task is not None:
            _fail_task(record, task, e, meta)
        return _Outcome(
            FailedTask(
                message_id=record.messageId,
                task_id=task.id if task else None,
                error=str(e),
            )
        )

    except Exception as e:
        logger.exception(f"Unexpected error processing message {record.messageId}")
        if task is not None:
            _fail_task(record, task, e, meta)
        return _Outcome(
            FailedTask(
                message_id=record.messageId,
                task_id=task.id if task else None,
                error=f"Unexpected error: {e}",
            )
        )


_init_done = False


def _load_init_modules() -> None:
    """Import the ``INIT_MODULES`` once (they register signals and the like)."""
    global _init_done
    if _init_done:
        return
    _init_done = True
    for name in settings.INIT_MODULES:
        try:
            importlib.import_module(name)
            logger.info(f"Imported init module {name}")
        except Exception:
            logger.exception(f"Could not import init module {name}")


def _process_all(records: list[SQSRecord], deadline: float | None) -> list[_Outcome]:
    """Process the records one after the other, or in threads (BATCH_CONCURRENCY)."""
    workers = min(settings.BATCH_CONCURRENCY, len(records))
    if workers <= 1:
        return [_process_record(record, deadline) for record in records]

    with ThreadPoolExecutor(max_workers=workers) as pool:
        # each record runs in a copy of the context (trace id, runtime...)
        futures = [
            pool.submit(
                contextvars.copy_context().run, _process_record, record, deadline
            )
            for record in records
        ]
        return [future.result() for future in futures]


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda handler for processing Celery Broker events

    Every record of the batch is processed independently. Failures are
    reported in the response and, when the task state could not be stored in
    the backend, in ``batchItemFailures`` so SQS delivers the message again
    (requires ``ReportBatchItemFailures`` in the event source mapping).

    Args:
        event: AWS Lambda event (only SQS is supported by now).
        context: AWS Lambda context.

    Returns:
        dict[str, Any]: A serialized ``LambdaResponse``.
    """

    # Logging: Generate KSUID as trace_id and assign it to the context
    trace_id_context.set(str(Ksuid()))

    # When AWS stops this invocation (None outside Lambda, e.g. in tests)
    seconds_left = remaining_seconds(context)
    deadline = None if seconds_left is None else time.monotonic() + seconds_left

    try:
        logger.debug(f"Processing lambda event with context: {context}")

        # TODO: Only SQS managed by now, add more event types
        sqs_event: SQSEvent = SQSEvent.from_lambda(event)
        logger.debug(f"Received {len(sqs_event.Records)} records")

        processed_tasks: list[ProcessedTask] = []
        failed_tasks: list[FailedTask] = []
        skipped_tasks: list[SkippedTask] = []
        delayed_tasks: list[DelayedTask] = []
        retry_items: list[BatchItemFailure] = []

        _load_init_modules()

        for record, outcome in zip(
            sqs_event.Records,
            _process_all(sqs_event.Records, deadline),
            strict=True,
        ):

            if isinstance(outcome.result, ProcessedTask):
                processed_tasks.append(outcome.result)
                continue

            if isinstance(outcome.result, SkippedTask):
                skipped_tasks.append(outcome.result)
                continue

            if isinstance(outcome.result, DelayedTask):
                delayed_tasks.append(outcome.result)
                continue

            failed_tasks.append(outcome.result)
            if outcome.retry:
                retry_items.append(BatchItemFailure(itemIdentifier=record.messageId))

        return LambdaResponse(
            status="completed",
            processed_messages=len(processed_tasks),
            failed_messages=len(failed_tasks),
            skipped_messages=len(skipped_tasks),
            delayed_messages=len(delayed_tasks) if delayed_tasks else None,
            delayed_tasks=delayed_tasks if delayed_tasks else None,
            skipped_tasks=skipped_tasks if skipped_tasks else None,
            processed_tasks=processed_tasks if processed_tasks else None,
            failed_tasks=failed_tasks if failed_tasks else None,
            batchItemFailures=retry_items,
        ).model_dump()

    except EventDecodeException as e:
        return LambdaResponse(
            status="error",
            message=e.message,
            details=e.detail,
        ).model_dump()

    except Exception as e:
        logger.exception("Unexpected error in lambda handler")
        return LambdaResponse(
            status="error",
            message=f"General error: {str(e)}",
            details=str(e),
        ).model_dump()

    finally:
        # Clear context before finishing the function
        trace_id_context.set(None)
