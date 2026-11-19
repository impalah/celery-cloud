Client: revoking tasks
======================

A Celery client cannot revoke a task of this runner on its own: ``revoke()`` broadcasts to
workers, and there are none. ``celery_cloud.client.install`` makes it work through the
result backend. It is **optional** and the only place where the client needs the
``celery-cloud`` package (it only needs ``boto3``, no runner settings).

.. literalinclude:: ../examples/client/revoke.py
   :language: python
   :caption: revoke.py

How it works
------------

``install(app)`` replaces ``app.control.revoke``, so ``result.revoke()`` and
``app.control.revoke(task_id)`` both work. It reads the Region and table from the app's
``result_backend`` (``dynamodb://@region/table``) and the ``result_serializer``.

* If the task **has not started** the helper creates its item with ``REVOKED`` and a
  ``revoked`` flag. When the message arrives the runner finds it and skips the task:
  ``result.state`` is ``REVOKED`` and ``get()`` raises ``TaskRevokedError``.
* If the task **already exists** (running or finished) only the flag is set. A task that
  checks ``self.is_revoked()`` between its steps can stop; nothing interrupts a running
  function, and ``terminate=True`` / ``signal=`` are accepted but do not kill anything.

Revoking before the task is queued is also possible: revoke by id, then send the message.

Permissions
-----------

The identity of the client also needs ``dynamodb:PutItem`` and ``dynamodb:UpdateItem`` on
the table (:doc:`../infrastructure/iam-roles`).

Without ``install``
-------------------

Everything else keeps working. ``result.revoke()`` is then accepted but has no effect,
except that Celery may try to reach a broadcast channel and wait for a timeout.
