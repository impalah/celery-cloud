Server: local tasks
===================

A *local task* is a Python function packaged inside the runner image. It is the
simplest and cheapest option: no extra Lambda invocation.

The contract
------------

.. tip::

   Functions can also be written with the Celery-like API (natural arguments, retries,
   progress, time limits): see :doc:`server-task-api`. Both styles work in the same
   runner.

A local task is a function with exactly **two positional parameters**: the list of
positional arguments and the dict of keyword arguments sent by the client. It
returns the result, which must be JSON serialisable (anything else is stored as
its ``str()``). Raise any exception to make the task fail.

.. literalinclude:: ../examples/server/calculator.py
   :language: python
   :caption: calculator.py

A local task runs inside the runner, so it is bound by the **15 minute** limit of a
Lambda function (see :ref:`the execution time limit <execution-time-limit>`).

Use ``celery_cloud.logging.logger`` so your log lines carry the ``trace_id`` of the
invocation (see :doc:`../api/logging`).

Register the tasks
------------------

``TASKS`` maps the Celery task name to the function: ``task://<module>/<function>``.
The module path is the one Python can import inside the image.

.. literalinclude:: ../examples/server/env.json
   :language: json
   :caption: env.json (environment of the Lambda function)

Package the tasks
-----------------

Build an image on top of the runner image and copy your modules next to the
handler:

.. literalinclude:: ../examples/server/Dockerfile
   :language: dockerfile
   :caption: Dockerfile

.. code-block:: bash

   docker build --platform linux/amd64 --provenance=false \
     -t 123456789012.dkr.ecr.eu-central-1.amazonaws.com/celery-cloud-runner:2 .
   docker push 123456789012.dkr.ecr.eu-central-1.amazonaws.com/celery-cloud-runner:2

   aws lambda update-function-code --function-name celery-cloud-runner \
     --image-uri 123456789012.dkr.ecr.eu-central-1.amazonaws.com/celery-cloud-runner:2

The infrastructure around it (queue, table, role, function, event source mapping)
is explained in :doc:`../infrastructure`.

If your tasks live in a package with its own dependencies, install it in the image
instead of copying single files (``RUN pip install --no-cache-dir .``) and use the
dotted module path: ``task://my_package.domain.calculator/add``.

Tasks with structured data
--------------------------

Celery serialises arguments as JSON, so a pydantic model arrives as a plain dict:
validate it on entry and return ``model_dump()``. The client side of this example
is :doc:`client-structured`.

.. literalinclude:: ../examples/server/reports.py
   :language: python
   :caption: reports.py

What the runner stores
----------------------

For ``calculator.add`` with ``args=[10, 3]`` and ``kwargs={"extra": 5}`` the item in
DynamoDB holds a ``result`` like this (JSON, decoded):

.. code-block:: json

   {
     "status": "SUCCESS",
     "result": 18,
     "traceback": null,
     "children": [],
     "date_done": "2025-01-01T10:00:00.123456+00:00",
     "task_id": "8d58fa0a-f181-47ff-83e9-9ddfd2ee8af9"
   }

If the function raises ``ValueError("subtract needs at least 2 values")``:

.. code-block:: json

   {
     "status": "FAILURE",
     "result": {
       "exc_type": "ValueError",
       "exc_message": ["subtract needs at least 2 values"],
       "exc_module": "builtins"
     },
     "traceback": "Traceback (most recent call last): ..."
   }

The client receives a real ``ValueError`` with that message (Celery rebuilds the class
from ``exc_module`` and ``exc_type``).
