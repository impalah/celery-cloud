Server: debugging locally
=========================

You can run the handler on your machine, with your task code, without deploying and
without AWS credentials for the queue.

The debug server
----------------

``celery_cloud.debug_server`` is a small FastAPI application that exposes
``POST /lambda``: it feeds the JSON body to ``lambda_handler`` as the event. It
needs the development dependencies (``uv sync`` in a clone of the repository, which
installs FastAPI, uvicorn and debugpy).

.. code-block:: bash

   export TASKS='{"calculator.add": "task://calculator/add"}'
   export CELERY_BACKEND_TABLE=lambda-runner-tasks
   export CELERY_BACKEND_REGION=eu-central-1
   export PYTHONPATH=pages_source/examples/server   # where calculator.py lives
   uv run uvicorn celery_cloud.debug_server:app

.. note::

   The handler writes to DynamoDB, so you need a table: the real one with
   credentials, or a local emulator (DynamoDB Local, or ``moto_server`` together
   with ``AWS_ENDPOINT_URL``).

Send an SQS event
-----------------

An SQS event holds the Celery message in ``Records[].body``. The easiest way to get
a realistic one is to take it from a test: ``tests/conftest.py::build_sqs_record``
builds it. Post it to the server:

.. code-block:: bash

   curl -X POST http://127.0.0.1:8000/lambda \
     -H "Content-Type: application/json" -d @sqs_event.json

Attach a debugger
-----------------

With ``DEBUG_MODE=true`` the server waits for a ``debugpy`` client on
``SERVER_DEBUG_PORT`` (5890, on ``127.0.0.1``). Example ``launch.json`` for VS Code:

.. code-block:: json

   {
     "version": "0.2.0",
     "configurations": [
       {
         "name": "Attach to FastAPI (uv)",
         "type": "debugpy",
         "request": "attach",
         "connect": {"host": "localhost", "port": 5890},
         "pathMappings": [
           {"localRoot": "${workspaceFolder}", "remoteRoot": "${workspaceFolder}"}
         ]
       }
     ]
   }

.. warning::

   ``debugpy`` lets whoever connects run code. It listens on ``127.0.0.1`` by
   default; set ``DEBUG_HOST=0.0.0.0`` only inside a container on a trusted
   network.

Run the container locally
-------------------------

The AWS base image includes the Lambda Runtime Interface Emulator:

.. code-block:: bash

   docker run --rm -p 9000:8080 --env-file .env <image>
   curl -X POST http://localhost:9000/2015-03-31/functions/function/invocations \
     -d @sqs_event.json

Unit-testing your tasks
-----------------------

Local tasks are plain functions, so they are tested without any AWS involvement:

.. code-block:: python

   from calculator import add, subtract
   import pytest

   def test_add():
       assert add([10, 3], {"extra": 5}) == 18

   def test_subtract_needs_two_values():
       with pytest.raises(ValueError):
           subtract([5], {})
