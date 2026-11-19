Concepts and behaviour
======================

This page explains what the runner does with every message. Read it once: it
answers most "why did my task...?" questions.

How a message is processed
--------------------------

For every record of an SQS batch, **independently** of the others (one bad
message never blocks the rest of the batch), the runner:

1. Decodes the SQS record and the Celery message inside it. Arguments are read
   from the message **body** (``[args, kwargs, embed]``). JSON, MessagePack and YAML
   (and compression) are understood, see `Serializers and compression`_.
2. If the task has a future ``eta`` it is **held**: the message goes back to the queue
   with a delay (see `Delayed tasks`_) and nothing else happens yet.
3. Registers the task in DynamoDB with a *conditional write* and the state
   ``STARTED``. If the task id already exists the message is a duplicate (or a task
   that was revoked) and it is skipped; the message of a *retry* takes the task over
   (see `Retries`_).
4. Looks the task **name** up in ``TASKS`` (the allowlist) and executes it:
   ``task://`` calls a Python function, ``lambda://`` invokes a Lambda function.
5. Stores how it ended: ``SUCCESS`` with the result, ``FAILURE`` with the exception,
   or ``RETRY``.
6. Sends the messages that must follow: callbacks, the next step of a chain, the
   body of a chord (see `Workflows`_).
7. Returns a response with counters and the lists of processed, failed, skipped and
   delayed tasks.

Task states
-----------

The runner writes the standard Celery states so that ``AsyncResult`` works as
usual:

.. list-table::
   :header-rows: 1
   :widths: 18 82

   * - State
     - Meaning
   * - ``STARTED``
     - The message was received and the task is running.
   * - ``SUCCESS``
     - The task returned. ``result.get()`` returns its value.
   * - ``FAILURE``
     - The task raised, was not listed in ``TASKS``, exceeded a time limit, or could
       not be decoded. ``result.get()`` raises **the original exception**
       (``except ValueError`` works; a class the client cannot import is recreated
       with the same name and arguments); ``result.traceback`` holds the traceback
       of the runner.
   * - ``RETRY``
     - The task asked to run again (``self.retry()`` or ``autoretry_for``); its
       message was sent again. ``result.result`` is the exception that caused it.
   * - ``REVOKED``
     - The task arrived after its ``expires`` time, or the client revoked it, and it
       was not executed.
   * - ``REJECTED``
     - The task raised ``Reject`` without ``requeue``: the message was dropped.
   * - *your own*
     - Whatever the task stored with ``self.update_state(state=...)``, for example
       ``PROGRESS`` (``result.info`` is the ``meta`` it gave). ``Ignore`` leaves it
       as the task set it.

Failures never block the batch and are **not** retried by SQS: they are reported
as ``FAILURE``, like Celery does.

Celery options honoured by the runner
-------------------------------------

* ``ignore_result``: nothing is written to the backend (not even failures).
* ``soft_time_limit`` / ``time_limit``: see `Execution time limit`_.
* ``expires``: a task received after its expiration time is not executed and is
  stored as ``REVOKED``.
* ``eta`` / ``countdown``: the task is held until then, see `Delayed tasks`_.
* ``link``, ``link_error``, ``chain``, ``chord``, ``group``, ``map``, ``starmap`` and
  ``chunks``: see `Workflows`_.

Results that JSON cannot represent (``datetime``, ``Decimal``...) are stored as
their ``str()``. A result larger than about 380 KB does not fit in a DynamoDB item
(400 KB limit): the task is stored as ``FAILURE`` with a
``ResultTooLargeException`` explaining the size, and it is not retried.

.. _backend-item-format:

Backend item format
-------------------

The runner writes the same item layout as Celery's own DynamoDB backend, so both
can share the table:

.. list-table::
   :header-rows: 1
   :widths: 15 10 75

   * - Attribute
     - Type
     - Content
   * - ``id``
     - String
     - Hash key: ``b'celery-task-meta-<task id>'`` (the string form of a bytes
       object, which is how Celery builds it).
   * - ``result``
     - Binary
     - JSON with ``status``, ``result``, ``traceback``, ``children``,
       ``date_done`` and ``task_id``. For ``FAILURE`` the ``result`` is
       ``{"exc_type", "exc_message", "exc_module"}``.
   * - ``timestamp``
     - Number
     - Time of the last change.
   * - ``ttl``
     - Number
     - Epoch second after which DynamoDB may delete the item (see below).
   * - ``attempt``
     - Number
     - **Not Celery's.** Only written for a retry: the ``retries`` of the message that
       owns the task (see `Retries`_). Celery ignores it.
   * - ``revoked``
     - Boolean
     - **Not Celery's.** Set by ``celery_cloud.client.revoke`` (see `Revoking`_).

For chords the runner also reads and updates the two items that Celery's backend
keeps (``b'celery-taskset-meta-<group id>'`` with the ids of the group and
``b'chord-unlock-<group id>'`` with the ``chord_count`` counter) and deletes them when
the chord is done.

.. _result-expiration:

Result expiration
-----------------

Every item carries a ``ttl`` attribute: the epoch second after which the item can
be deleted, ``RESULT_TTL_SECONDS`` (default 24 hours) after the **last change of
state**. It is the same attribute, type and unit that Celery's DynamoDB backend
uses.

The attribute does nothing by itself: **DynamoDB only deletes expired items once
TTL is enabled on the table for the attribute** ``ttl`` (see
:doc:`infrastructure/dynamodb-table`). Until then results are kept forever. Set
``RESULT_TTL_SECONDS=0`` to stop writing the attribute.

DynamoDB deletes expired items some time after they expire, not at the exact
second. Failed tasks and tasks stuck in ``STARTED`` expire too.

.. warning::

   Once an item is deleted the runner no longer remembers that task id, so a very
   late redelivery of the same message would run it again. Keep
   ``RESULT_TTL_SECONDS`` longer than the retention period of the queue if that
   matters to you.

.. _concepts-delayed:

Delayed tasks
-------------

``apply_async(countdown=30)`` and ``eta=...`` are honoured. SQS can delay a message at
most 15 minutes, so a task that is due later is held in steps: each time the runner
receives it before its ``eta`` it sends the **same message** back to the queue with
the longest delay that does not overshoot (rounded up: a task never runs early), and
deletes the received one. The task is not registered meanwhile, so the client sees it
as ``PENDING``, as with a Celery worker that has not reached it yet.

* One extra SQS request every 15 minutes while it waits: waiting a day costs about a
  hundred messages.
* The precision is a second or two plus the SQS latency.
* The runner needs ``sqs:SendMessage`` on the queue (see :doc:`infrastructure/iam-roles`).
  If the message cannot be sent back, the original is returned to SQS
  (``batchItemFailures``) and nothing is lost.
* For exact schedules weeks ahead, EventBridge Scheduler is a better tool (see
  :doc:`infrastructure/periodic-tasks`).

.. _retries:

Retries
-------

A decorated task (see :doc:`user-guide/server-task-api`) can ask to run again with
``raise self.retry(exc=exc, countdown=30)`` or declare ``autoretry_for``. The runner
sends the same message again, with ``retries`` increased and an ``eta``, stores the
state ``RETRY`` and ends the invocation successfully (SQS must not redeliver it).
``max_retries`` (default 3) counts the retries; when they run out the last exception
is the ``FAILURE``.

The retry has the **same task id**, so it must not be discarded as a duplicate. The
conditional write that protects against duplicates takes this into account: the item
records the ``retries`` of the message that owns the task (the extra ``attempt``
attribute) and a message with a *higher* ``retries`` takes the task over, once (the
update is conditional too). A second copy of the same retry, or a late duplicate of the
original message, is skipped as usual.

If the retry message cannot be sent the task is stored as ``FAILURE`` with the error
that caused the retry.

.. _workflows:

Workflows
---------

Celery's worker starts the next tasks of a workflow when a task ends. The runner does
the same, sending the next messages to the queue (it needs ``sqs:SendMessage``):

* ``link`` callbacks receive the result of the task as first argument.
* ``chain``: the next task receives the result of the previous one. If a task fails
  the chain stops.
* ``group``: tasks are independent messages, nothing special is needed.
* ``chord``: every task of the header counts itself in the backend when it ends
  (Celery's own ``chord_count`` counter); the last one collects the results of the
  whole header, in order, and sends the body with the list as its only argument. If a
  header task failed, the body is stored as ``FAILURE`` with ``ChordError``
  (``Dependency <id> raised ValueError(...)``) and its ``link_error`` callbacks run.
* ``link_error``: the errback receives the id of the failed task (the classic form of
  Celery errbacks; the new-style ``(request, exc, traceback)`` form is not used).
* ``map``, ``starmap`` and ``chunks`` run as ``celery.map`` / ``celery.starmap``
  tasks: the runner calls the named task once per item inside the same invocation
  (the task must be in ``TASKS``). All the items must fit in the time limit.

A callback can go to another queue with ``options.queue``. If sending the next
messages fails (SQS unavailable) the finished task keeps its ``SUCCESS`` and the
problem is only logged: the callback is lost. The AWS SDK already retries these calls
a few times.

Revoking
--------

``result.revoke()`` of a plain Celery client does nothing (it broadcasts to workers
that do not exist). After ``celery_cloud.client.install(app)`` (see
:doc:`user-guide/client-revoke`) it writes a ``REVOKED`` result with a ``revoked``
flag to the backend:

* A task that **has not started** is never executed (the runner finds the flag when it
  registers the task).
* A task that is **running** is only flagged: a Python function cannot be stopped
  safely from outside. It stops if its code checks ``self.is_revoked()``.

Serializers and compression
---------------------------

JSON works out of the box. MessagePack and YAML need an extra
(``pip install celery-cloud[msgpack]`` / ``[yaml]``, in the runner image). Compression
with ``gzip`` (which kombu implements as zlib; a real gzip stream is accepted too),
``bzip2`` and ``lzma`` is understood. ``pickle`` is refused on purpose: unpickling a
message from a queue executes arbitrary code. Brotli and zstd are not supported.

Results are written with the serializer set in ``RESULT_SERIALIZER``, which must match
the client's ``result_serializer`` (default ``json``). Result compression is not
supported.

.. _duplicates:

Duplicate deliveries
--------------------

SQS delivers messages at least once. Because each task is registered with a
conditional write, only the first delivery of a task id is executed; later
deliveries are reported in ``skipped_tasks`` and discarded. Consequences:

* If the runner dies while a task is ``STARTED`` (for example it runs out of memory;
  timeouts are handled by the time limits), SQS redelivers the message but
  it is discarded as a duplicate and the task stays ``STARTED``. **Give the client
  a timeout** (``result.get(timeout=...)``).
* Tasks sent with ``ignore_result`` have no record in the backend, so they cannot
  be de-duplicated.
* Re-sending a task with an already used task id is treated as a duplicate.

Partial batch responses
-----------------------

When the state of a task **could not be stored in the backend** (for example
DynamoDB is unavailable) the message id is returned in ``batchItemFailures``, so
SQS delivers it again. This only works when the event source mapping has
``ReportBatchItemFailures`` enabled (see
:doc:`infrastructure/lambda-function`). Without it, SQS deletes every message of a
batch whose invocation did not raise, so those messages are not retried.

A record is also returned to SQS when it could not be started because the Lambda
timeout is too close (see `Execution time limit`_), when a ``Reject(requeue=True)``
asks for it, or when a task due later could not be sent back to the queue.


Remote Lambda tasks
-------------------

``lambda://<function-arn>`` invokes the function synchronously with
``{"args": [...], "kwargs": {...}}`` and uses the ``body`` key of the response when
present.

* Invocation errors (throttling, network) are retried up to ``MAX_ATTEMPTS`` times.
* An error **returned by the function** is never retried: the function already ran.
* Each function has its own circuit breaker (``CB_FAIL_MAX``, ``CB_RESET_TIMEOUT``).

.. _execution-time-limit:

Execution time limit
--------------------

**Every task must finish within the maximum timeout of an AWS Lambda function:
15 minutes (900 seconds).** The runner is a Lambda function, so this applies to
local tasks (``task://``) and to remote ones (``lambda://``) alike.

The runner does not wait for AWS to kill the function. Every task runs with a
**hard limit of ``timeout - TIMEOUT_MARGIN_SECONDS``** (10 s by default): when it is
reached the task is interrupted with ``TimeLimitExceeded`` and stored as ``FAILURE``,
so the client gets an answer instead of a task stuck in ``STARTED``. Records of a
batch that would start with less than the margin left are not started and go back to
SQS (``batchItemFailures``). The interruption uses ``SIGALRM``: it stops Python code
and blocking calls, but a C extension that never returns control cannot be
interrupted (AWS still kills the function then, the task stays in ``STARTED``).

Time limits of the task
~~~~~~~~~~~~~~~~~~~~~~~

The client can ask for shorter limits with Celery's own options; the runner honours
them and the smaller value wins:

.. code-block:: python

   add.apply_async(args=(1, 2), soft_time_limit=30, time_limit=60)

* ``soft_time_limit``: after that many seconds ``SoftTimeLimitExceeded`` is raised
  inside the task, which can catch it to clean up.
* ``time_limit``: after that many seconds ``TimeLimitExceeded`` is raised; if the
  task ignored the soft limit it ends here as ``FAILURE``.

Both exceptions are reported as ``celery.exceptions.SoftTimeLimitExceeded`` and
``celery.exceptions.TimeLimitExceeded``, so ``except SoftTimeLimitExceeded`` works on
the client. They are also importable from ``celery_cloud.exceptions`` for task code.

For remote tasks the limit is tighter, because the runner waits for the remote
function synchronously, and the runner's own timeout (also at most 900 s) has to
cover that wait plus its own work. In practice a remote function should finish
comfortably under 15 minutes, and its timeout must be **lower** than the runner's.

The timeouts that interact:

.. list-table::
   :header-rows: 1
   :widths: 32 18 50

   * - Timeout
     - Maximum
     - Rule
   * - Runner function (``--timeout``)
     - 900 s
     - Longer than the slowest task (and than the remote function's timeout).
   * - Remote function (``lambda://``)
     - 900 s
     - Shorter than the runner's timeout.
   * - ``LAMBDA_INVOKE_TIMEOUT``
     - no AWS limit
     - How long the runner waits for a remote answer. Default 840 s (14 min), below
       the 900 s maximum of the runner so the failure is recorded instead of the
       whole invocation being killed. Lower it if your runner timeout is lower.
   * - SQS visibility timeout
     - 12 h
     - At least the runner's timeout (see :doc:`infrastructure/sqs-queue`).
   * - Client ``result.get(timeout=...)``
     - none
     - Your choice: always set it.

Work that can take longer than 15 minutes does not fit this runner. Split it into
steps that each fit (sending a new task for the next step), or start the long job
from a short task in a service meant for it (AWS Step Functions, ECS/Fargate, AWS
Batch) and have the client poll for its outcome.

Known limitations
-----------------

* Every task, local or remote, must finish in less than 15 minutes (see
  `Execution time limit`_).
* Only SQS events are supported.
* Celery's remote control (``inspect``, ``control``...) does not exist: there are no
  workers to ask. ``revoke`` works through the backend with a client helper.
* No ``celery beat``: schedule periodic tasks with EventBridge Scheduler (see
  :doc:`infrastructure/periodic-tasks`).
* ``pickle``, brotli and zstd are not supported; result compression neither.
* Results above about 380 KB are a ``FAILURE`` (DynamoDB item limit).

Differences from a Celery worker
--------------------------------

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Celery worker
     - This runner
   * - Pools, ``concurrency``, ``autoscale``, ``prefetch``
     - AWS scales invocations; ``BATCH_CONCURRENCY`` runs the records of a batch in
       threads
   * - ``self.retry``, ``autoretry_for``, ``max_retries``
     - Supported for tasks decorated with ``@celery_cloud.task`` (:ref:`retries`)
   * - Task class, ``base=``, ``Task.run``
     - Not supported: a task is a function
   * - Signals, ``on_success`` / ``on_failure`` / ``on_retry``
     - ``celery_cloud.signals`` and the same options of ``@task``
   * - ``rate_limit``
     - Not implemented: limit concurrency (``MaximumConcurrency`` of the event
       source mapping, reserved concurrency), see
       :doc:`infrastructure/queues-and-priorities`
   * - Queues, routing keys, priorities
     - One queue per event source mapping; priorities are separate queues
   * - Events, Flower
     - CloudWatch metrics (``METRICS_ENABLED``) and logs
   * - ``celery inspect`` / ``control``
     - Not available
