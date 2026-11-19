Task execution
==============

``TaskExecutor`` chooses an execution strategy from the scheme of the route
(``task://`` or ``lambda://``). To support a new scheme, subclass
``TaskExecutionStrategy`` and register it in ``TaskExecutor.strategies``.

Executor
--------

.. automodule:: celery_cloud.runners.task_executor
   :members:
   :show-inheritance:

Strategy interface
------------------

.. automodule:: celery_cloud.runners.task_execution_strategy
   :members:
   :show-inheritance:

Local strategy (``task://``)
----------------------------

.. automodule:: celery_cloud.runners.local_strategy
   :members:
   :show-inheritance:

Lambda strategy (``lambda://``)
-------------------------------

.. automodule:: celery_cloud.runners.lambda_strategy
   :members:
   :show-inheritance:
