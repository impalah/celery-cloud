Exceptions
==========

All the exceptions of the runner derive from ``RunnerBaseException``. The
handler never lets them escape: it converts them into a ``FAILURE`` state in the
backend, a failed task in the response, or an entry in ``batchItemFailures``
(see :doc:`../concepts`).

.. automodule:: celery_cloud.exceptions.runner_base_exception
   :members:
   :show-inheritance:

.. automodule:: celery_cloud.exceptions.runner_exceptions
   :members:
   :show-inheritance:

Exceptions for task code
------------------------

Raised or used *inside* tasks (``from celery_cloud import ...``). The client receives the
Celery classes of the same name.

.. automodule:: celery_cloud.exceptions.task_exceptions
   :members:
   :show-inheritance:
