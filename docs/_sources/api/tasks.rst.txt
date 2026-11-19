Task API
========

``from celery_cloud import task, Retry, Ignore, Reject`` (see :doc:`../user-guide/server-task-api`).

.. automodule:: celery_cloud.tasks
   :members: task, TaskOptions, TaskRequest, TaskContext, get_options, backoff_countdown, call_task_function
   :show-inheritance:

Runtime
-------

The services a running task can reach (custom states, revocation), published by the runner
for the duration of the task.

.. automodule:: celery_cloud.runtime
   :members:
