Result backend model
====================

``TaskModel`` is the `PynamoDB <https://pynamodb.readthedocs.io>`_ model of the
DynamoDB table. It writes the same item layout as Celery's own DynamoDB backend
(see :ref:`backend-item-format`).

.. automodule:: celery_cloud.models.task_model
   :members:
   :show-inheritance:
   :exclude-members: result

``TaskModel.result`` is a binary attribute that holds the JSON of the Celery meta
(``status``, ``result``, ``traceback``, ``children``, ``date_done``, ``task_id``).

Chords
------

The group and counter items that Celery's DynamoDB backend keeps for chords.

.. automodule:: celery_cloud.models.canvas_model
   :members:
   :show-inheritance:
