Celery Cloud Documentation
==========================

**Celery workers without servers.** Celery Cloud runs your
`Celery <https://docs.celeryq.dev>`_ tasks on AWS Lambda. Your application keeps
using the normal Celery client; instead of operating a fleet of always-on
workers, a Lambda function consumes the queue, executes the task and stores the
result where Celery expects it.

.. image:: https://img.shields.io/pypi/v/celery-cloud.svg
   :target: https://pypi.org/project/celery-cloud/
   :alt: PyPI Version

.. image:: https://img.shields.io/pypi/pyversions/celery-cloud.svg
   :target: https://pypi.org/project/celery-cloud/
   :alt: Python Version

.. image:: https://img.shields.io/badge/license-MPL--2.0-blue.svg
   :target: https://github.com/impalah/celery-cloud/blob/main/LICENSE
   :alt: License

What is Celery Cloud?
---------------------

A classic Celery deployment needs worker processes running (and being paid for,
patched and scaled) around the clock, even when the queue is empty. With Celery
Cloud:

* **No workers to manage.** AWS invokes the runner only when there are messages
  in the queue and scales it for you.
* **No change in the client.** Your code still calls ``task.delay(...)`` or
  ``task.apply_async(...)`` and reads ``AsyncResult``, using Celery's own SQS
  broker and DynamoDB result backend.
* **Your tasks can live anywhere.** A task can be a Python function packaged with
  the runner (a *local task*), or an existing AWS Lambda function that the runner
  calls for you (a *remote task*).
* **Most of what a Celery worker does.** Retries with backoff, ``eta`` / ``countdown``,
  time limits, progress states, ``link`` / ``chain`` / ``group`` / ``chord``, ``map`` /
  ``starmap`` / ``chunks``, signals, ``revoke`` and MessagePack / YAML / compression
  (see :doc:`concepts` for what differs from a real worker).
* **Safe by construction.** Only the task names you list can run; a message
  cannot choose which code is executed.

.. mermaid::

   graph LR
       Client["Celery client<br/>(your application)"]
       SQS["Amazon SQS<br/>(broker)"]
       Runner["celery-cloud runner<br/>(AWS Lambda)"]
       Local["Local task<br/>task://module/function"]
       Remote["Remote Lambda<br/>lambda://function-arn"]
       DDB["DynamoDB<br/>(result backend)"]

       Client -- "1. apply_async" --> SQS
       SQS -- "2. event source mapping" --> Runner
       Runner -- "3a. call" --> Local
       Runner -- "3b. invoke" --> Remote
       Runner -- "4. STARTED / SUCCESS / FAILURE" --> DDB
       Client -- "5. result.get()" --> DDB

Quick Start
-----------

1. **Create the infrastructure**: an SQS queue, a DynamoDB table, an ECR
   repository and a Lambda function connected to the queue. See
   :doc:`infrastructure` for the step by step guide.

2. **Write a task** and package it with the runner. A local task receives the
   list of positional arguments and the dict of keyword arguments:

   .. code-block:: python

      # my_tasks.py
      def add(args: list, kwargs: dict) -> int:
          return sum(args) + kwargs.get("extra", 0)

   Tell the runner where the task runs with the ``TASKS`` environment variable
   of the function (see :doc:`configuration`):

   .. code-block:: json

      {"tasks.add": "task://my_tasks/add"}

3. **Send the task from your application** with a plain Celery client
   (``pip install "celery[sqs,dynamodb]"``). The client does not need
   ``celery-cloud``:

   .. code-block:: python

      from celery import Celery

      REGION = "eu-central-1"
      QUEUE_NAME = "lambda-runner-queue"
      QUEUE_URL = "https://sqs.eu-central-1.amazonaws.com/123456789012/lambda-runner-queue"

      app = Celery("task_client")
      app.conf.update(
          broker_url="sqs://",
          result_backend=f"dynamodb://@{REGION}/lambda-runner-tasks",
          task_default_queue=QUEUE_NAME,
          broker_connection_retry_on_startup=True,
          broker_transport_options={
              "region": REGION,
              "predefined_queues": {QUEUE_NAME: {"url": QUEUE_URL}},
          },
      )

      @app.task(name="tasks.add")
      def add(x: int, y: int) -> int:
          raise NotImplementedError  # declaration only: never runs on the client

      result = add.apply_async((10, 3))
      print(result.get(timeout=60))  # 13

The :doc:`user-guide` walks through complete examples for both sides.

Contents
--------

.. toctree::
   :maxdepth: 2
   :caption: Getting Started

   installation
   configuration
   concepts

.. toctree::
   :maxdepth: 2
   :caption: User Guide

   user-guide

.. toctree::
   :maxdepth: 2
   :caption: Infrastructure

   infrastructure

.. toctree::
   :maxdepth: 2
   :caption: Reference

   api

Indices and tables
------------------

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
