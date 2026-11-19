Client: errors, timeouts and states
===================================

A task can fail, and the runner can disappear. The client has to cope with both.

.. literalinclude:: ../examples/client/errors.py
   :language: python
   :caption: errors.py

Failures
--------

When the task raises, or its name is not in ``TASKS``, the runner stores ``FAILURE``
with the exception in Celery's format. On the client:

* ``result.get()`` raises **the original exception** with its arguments: the task
  raised ``ValueError("subtract needs at least 2 values")`` and the client can
  ``except ValueError``. An exception class that the client cannot import is
  recreated with the same name and arguments, so ``except Exception`` and the
  message always work.
* ``result.traceback`` is the traceback captured **on the runner**.
* ``result.failed()`` / ``result.state == "FAILURE"`` let you check without
  raising; ``result.wait(propagate=False)`` returns the error instead of raising.

Always use a timeout
--------------------

A task that is too slow is stopped by the runner (see :ref:`execution-time-limit`) and
ends as ``FAILURE``. If the runner **dies** in the middle of a task (out of memory,
a crash), the item stays in ``STARTED`` and SQS'
redelivery is discarded as a duplicate (see :doc:`../concepts`). ``result.get()``
without ``timeout`` would wait forever. Use ``get(timeout=...)`` or poll with your
own deadline, as in the example.

``result.revoke()`` is accepted but does nothing: the runner implements no remote
control. To stop waiting, give up on the client side.

State reference
---------------

.. list-table::
   :header-rows: 1
   :widths: 20 80

   * - ``result.state``
     - What it means for the client
   * - ``PENDING``
     - No item yet: the message is queued, the runner has not received it, or the
       task id is unknown. Celery cannot tell these apart.
   * - ``STARTED``
     - The runner is executing it (or died while executing it).
   * - ``SUCCESS``
     - ``result.result`` holds the value.
   * - ``FAILURE``
     - ``result.result`` is the exception, ``result.traceback`` the traceback.
   * - ``REVOKED``
     - The task expired before it ran (``expires``).

Time limits
-----------

Ask for limits per call with Celery's options; the runner interrupts the task and the
client receives the Celery exceptions:

.. code-block:: python

   from celery.exceptions import SoftTimeLimitExceeded, TimeLimitExceeded

   result = divide.apply_async(args=(10, 4), soft_time_limit=30, time_limit=60)
   try:
       result.get(timeout=90)
   except SoftTimeLimitExceeded:
       print("the task ran longer than 30 s")
   except TimeLimitExceeded:
       print("the task was stopped after 60 s")

Retrying from the client
------------------------

The runner does not retry a failed task, and ``max_retries`` / ``self.retry()`` of
Celery tasks do not apply because the body never runs on the client. If a task is
safe to repeat, retry it from the application:

.. code-block:: python

   for attempt in range(3):
       result = divide.apply_async(args=(10, 4))
       outcome = result.wait(timeout=60, propagate=False)
       if not result.failed():
           break
   else:
       raise RuntimeError(f"divide kept failing: {outcome}")

Each attempt has a new task id, so the duplicate protection does not interfere.
