Client: retries, progress and delayed tasks
===========================================

What the client sees of a task that retries, reports progress, has a time limit or
runs later. The tasks are in :doc:`server-task-api`.

.. literalinclude:: ../examples/client/retries_and_progress.py
   :language: python
   :caption: retries_and_progress.py

Retries
-------

A retry is invisible to the client: the task goes through ``RETRY`` and ends as
``SUCCESS`` (or ``FAILURE`` with the last error). ``result.get(timeout=...)`` must be
long enough for the retries and their delays. While waiting, ``result.state`` is
``RETRY`` and ``result.info`` is the exception that caused it.

Progress
--------

A task that calls ``self.update_state(state="PROGRESS", meta={...})`` makes
``result.state == "PROGRESS"`` and ``result.info`` the ``meta`` dict. Polling at 0.3 s
shows most updates; the state is eventually consistent, so a very fast task may skip
some. The final state replaces the progress.

Countdown and eta
-----------------

.. code-block:: python

   task.apply_async(args=(1,), countdown=60)                      # in a minute
   task.apply_async(args=(1,), eta=datetime.now(UTC) + timedelta(hours=2))

The runner holds the task until it is due (see :ref:`Delayed tasks <concepts-delayed>`).
It stays ``PENDING`` meanwhile. Use ``expires=`` to discard the task if it was not run
in time (it is stored as ``REVOKED``).

Time limits per call
--------------------

.. code-block:: python

   task.apply_async(args=(10,), soft_time_limit=30, time_limit=60)

The client gets ``celery.exceptions.SoftTimeLimitExceeded`` or
``TimeLimitExceeded`` (see :doc:`client-errors`) unless the task handled the soft one.
