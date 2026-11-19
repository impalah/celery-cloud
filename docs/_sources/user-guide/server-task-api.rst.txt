Server: the Celery-like task API
================================

A function decorated with ``@celery_cloud.task`` is a *Celery-like* task. It keeps working
side by side with the plain ``f(args, kwargs)`` functions of
:doc:`server-local-tasks`: the decorator is what switches the convention.

.. list-table::
   :header-rows: 1
   :widths: 30 35 35

   * -
     - Plain function
     - ``@task`` function
   * - Signature
     - ``f(args, kwargs)``
     - ``f(x, y=0)``, the natural arguments (``f(self, x, y=0)`` with ``bind=True``)
   * - Retries, progress, revocation
     - no
     - yes (``self.retry``, ``self.update_state``, ``self.is_revoked``)
   * - Options
     - none
     - retries, backoff, time limits, hooks

The route in ``TASKS`` is the same: ``task://jobs/fetch``.

.. literalinclude:: ../examples/server/jobs.py
   :language: python
   :caption: jobs.py

The decorator
-------------

.. code-block:: python

   from celery_cloud import task

   @task                                     # natural arguments
   def add(x, y=0): ...

   @task(bind=True, max_retries=5)           # bind=True: the first parameter is the context
   def fetch(self, url): ...

The functions stay directly callable, which makes them easy to unit test (for a bound
task pass any object as ``self``).

.. list-table::
   :header-rows: 1
   :widths: 28 14 58

   * - Option
     - Default
     - Meaning
   * - ``bind``
     - ``False``
     - The first parameter is a ``TaskContext`` (``self``)
   * - ``max_retries``
     - ``3``
     - Retries before the task fails (``None`` = forever)
   * - ``default_retry_delay``
     - ``180``
     - Seconds before a retry that does not say otherwise
   * - ``autoretry_for``
     - ``()``
     - Exception classes that are retried automatically
   * - ``retry_backoff``
     - ``False``
     - ``True`` or a number: exponential delay ``factor * 2**retries``
   * - ``retry_backoff_max``
     - ``600``
     - Largest backoff, in seconds
   * - ``retry_jitter``
     - ``True``
     - Pick a random delay between 0 and the backoff
   * - ``soft_time_limit``, ``time_limit``
     - ``None``
     - Limits in seconds; a limit sent by the client wins
   * - ``on_success``, ``on_failure``, ``on_retry``
     - ``None``
     - Functions called at the end (see below)

The context (``self``)
----------------------

``self.request``
   ``id``, ``task``, ``args``, ``kwargs``, ``retries``, ``eta``, ``expires``,
   ``parent_id``, ``root_id``, ``group``, ``hostname``, ``delivery_info`` and the canvas
   fields.

``raise self.retry(exc=None, countdown=None, eta=None, max_retries=None)``
   Run the task again later. Without ``countdown`` or ``eta`` the delay is
   ``default_retry_delay``. When the retries run out it raises ``exc`` (or
   ``MaxRetriesExceededError`` if there is none). See :ref:`retries`.

``self.update_state(state=..., meta=...)``
   Store a custom state, e.g. ``PROGRESS``. The client reads it with ``result.state``
   and ``result.info``. Nothing is stored for tasks sent with ``ignore_result``.

``self.is_revoked()``
   True when the client revoked the task: use it between the steps of a long job.

Ending a task in other ways
---------------------------

.. code-block:: python

   from celery_cloud import Ignore, Reject

   raise Ignore()                      # end without touching the state (set it yourself first)
   raise Reject("busy", requeue=True)  # give the message back to SQS, the task runs again later
   raise Reject("not for me")          # drop the message, state REJECTED

Time limits
-----------

``soft_time_limit`` raises ``SoftTimeLimitExceeded`` inside the task, which can catch it
and return something (see ``export_report`` above); ``time_limit`` raises
``TimeLimitExceeded``. The limits of the client's ``apply_async`` win over the decorator's.
See :ref:`execution-time-limit` for how they interact with the Lambda timeout.

Hooks
-----

.. code-block:: python

   def on_failure(exc, task_id, args, kwargs, traceback):
       alert(f"{task_id} failed: {exc!r}")

   @task(on_failure=on_failure)
   def charge(order_id): ...

``on_success(retval, task_id, args, kwargs)``, ``on_failure(exc, task_id, args, kwargs,
traceback)`` and ``on_retry(exc, task_id, args, kwargs, traceback)`` have the arguments
of the Celery ``Task`` methods of the same name. A hook that raises is logged and
ignored.

Signals
-------

For hooks that apply to *every* task use ``celery_cloud.signals`` (``task_prerun``,
``task_postrun``, ``task_success``, ``task_failure`` and ``task_retry``). Connect the
receivers in a module and list it in ``INIT_MODULES`` so it is imported when the
function starts:

.. literalinclude:: ../examples/server/signals_setup.py
   :language: python
   :caption: signals_setup.py (``INIT_MODULES=signals_setup``)

Receivers are called with keyword arguments: declare ``**kwargs``. One that raises is
logged and does not affect the task. The arguments of each signal are in
:mod:`celery_cloud.signals`.

Metrics
-------

With ``METRICS_ENABLED=true`` the runner writes CloudWatch metrics through the Embedded
Metric Format, with the task name as dimension: ``TaskSucceeded``, ``TaskFailed``,
``TaskRetried``, ``TaskSkipped``, ``TaskDelayed``, ``TaskIgnored``, ``TaskRejected`` and
``TaskDuration`` (milliseconds). They need no extra IAM permission.
