Configuration
=============

The runner is configured with environment variables. On Lambda they are set on
the function; locally you can use an ``.env`` file (loaded with
``python-dotenv``). All values are read once, when the module is imported.

Integers and booleans are validated at start-up: an invalid value (for example
``DEBUG_MODE=maybe`` or ``CB_FAIL_MAX=five``) makes the runner fail immediately
with a clear message instead of misbehaving later.

Runner settings
---------------

.. list-table::
   :header-rows: 1
   :widths: 24 40 20 16

   * - Name
     - Description
     - Values
     - Default
   * - ``TASKS``
     - Task definition: where each task name runs (see below)
     - JSON object
     - ``{}``
   * - ``CELERY_BACKEND_REGION``
     - DynamoDB region
     - A string
     - ``eu-west-1``
   * - ``CELERY_BACKEND_TABLE``
     - Backend table name
     - A string
     - ``celery``
   * - ``RESULT_TTL_SECONDS``
     - Seconds a stored result is kept (see :ref:`result-expiration`). ``0`` = never
     - Integer >= 0
     - ``86400``
   * - ``MAX_ATTEMPTS``
     - Attempts to invoke a remote Lambda when the invocation itself fails
     - Integer
     - ``5``
   * - ``CB_FAIL_MAX``
     - Consecutive failures that open the circuit breaker of a remote Lambda
     - Integer
     - ``5``
   * - ``CB_RESET_TIMEOUT``
     - Seconds before an open circuit breaker lets one call through
     - Integer
     - ``60``
   * - ``TIMEOUT_MARGIN_SECONDS``
     - Seconds kept free before the Lambda timeout. A task is stopped (its ``FAILURE``
       stored) this long before AWS would kill the function; records that cannot start
       with that much time left go back to SQS (see :ref:`execution-time-limit`)
     - Integer >= 0
     - ``10``
   * - ``RESULT_EXTENDED``
     - Also store ``name``, ``args``, ``kwargs``, ``worker``, ``retries`` and ``queue``
       in the result, what Celery's ``result_extended`` setting reads.
       **Arguments may be sensitive.**
     - ``true`` / ``false``
     - ``false``
   * - ``BATCH_CONCURRENCY``
     - Records of a batch processed at the same time, in threads. ``1`` = one after
       the other. Above 1 the time limits cannot interrupt a task (signals only work
       in the main thread); only the check before starting each record applies
     - Integer >= 1
     - ``1``
   * - ``RESULT_SERIALIZER``
     - How results are written; must match the client's ``result_serializer``.
       ``msgpack`` and ``yaml`` need the extra of the same name in the image
     - ``json``, ``msgpack``, ``yaml``
     - ``json``
   * - ``INIT_MODULES``
     - Modules imported once when the function starts (to connect signal receivers).
       Comma separated
     - ``mod1,mod2``
     - empty
   * - ``METRICS_ENABLED``
     - Write CloudWatch metrics (Embedded Metric Format) to the log
     - ``true`` / ``false``
     - ``false``
   * - ``METRICS_NAMESPACE``
     - CloudWatch namespace of those metrics
     - A string
     - ``CeleryCloud``
   * - ``LAMBDA_INVOKE_TIMEOUT``
     - Seconds to wait for a remote Lambda to answer
     - Integer
     - ``840``

.. important::

   ``CELERY_BACKEND_REGION`` and ``CELERY_BACKEND_TABLE`` must point to the same
   table as the ``result_backend`` URL of the client.

Logging and debugging
---------------------

.. list-table::
   :header-rows: 1
   :widths: 24 40 20 16

   * - Name
     - Description
     - Values
     - Default
   * - ``LOG_LEVEL``
     - Log level of the application
     - ``DEBUG``, ``INFO``, ``WARNING``, ``ERROR``, ``CRITICAL``
     - ``INFO``
   * - ``LOG_FORMAT``
     - Log format (`loguru <https://loguru.readthedocs.io>`_ format string)
     - A string
     - Coloured, with ``trace_id``
   * - ``LOG_DIAGNOSE``
     - Dump local variables in tracebacks. **May leak task arguments to the logs**
     - ``true`` / ``false``
     - ``false``
   * - ``LOG_ENQUEUE``
     - Send log records through a queue (multiprocessing-safe)
     - ``true`` / ``false``
     - ``false``
   * - ``DEBUG_MODE``
     - Wait for a ``debugpy`` client when ``celery_cloud.debug_server`` starts
     - ``true`` / ``false``
     - ``false``
   * - ``DEBUG_HOST``
     - Interface ``debugpy`` listens on. Do not expose it on untrusted networks
     - A host / IP
     - ``127.0.0.1``
   * - ``SERVER_DEBUG_PORT``
     - Port ``debugpy`` listens on
     - Integer
     - ``5890``

.. _task-definition:

Task definition (``TASKS``)
---------------------------

``TASKS`` is a JSON dictionary. The key is the name of the task **as sent by
Celery**, and the value is a URL that says where it runs:

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - URL
     - Meaning
   * - ``task://<module>/<function>``
     - Call ``<function>`` of the Python module ``<module>``, which must be
       importable inside the runner image. The module can be a dotted path
       (``task://my_pkg.domain.restar/restar``).
   * - ``lambda://<function-arn>``
     - Invoke the Lambda function with that ARN (an alias or version suffix is
       accepted).

.. code-block:: json

   {
     "tasks.add": "task://my_tasks/add",
     "tasks.multiply": "lambda://arn:aws:lambda:eu-central-1:123456789012:function:multiply"
   }

Whatever the route, a task has at most **15 minutes** to finish (the AWS Lambda
limit; see :ref:`execution-time-limit`).

An invalid ``TASKS`` (not JSON, not an object, or a value without ``scheme://``)
stops the runner at start-up. A task whose name is **not** listed is stored as
``FAILURE`` and never runs: ``TASKS`` is an allowlist.

Setting ``TASKS`` on a function
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The value is JSON inside JSON, so avoid shell quoting by using a file:

.. code-block:: json

   {
     "Variables": {
       "TASKS": "{\"tasks.add\": \"task://my_tasks/add\"}",
       "CELERY_BACKEND_TABLE": "lambda-runner-tasks",
       "CELERY_BACKEND_REGION": "eu-central-1"
     }
   }

.. code-block:: bash

   aws lambda update-function-configuration \
     --function-name celery-cloud-runner \
     --environment file://env.json

Client configuration
--------------------

The Celery client is configured with Celery's own settings; the ones that matter
for Celery Cloud are:

.. list-table::
   :header-rows: 1
   :widths: 32 68

   * - Setting
     - Value
   * - ``broker_url``
     - ``sqs://``
   * - ``broker_transport_options["predefined_queues"]``
     - ``{QUEUE_NAME: {"url": QUEUE_URL}}``. The queue must already exist: the
       client does not create it.
   * - ``broker_transport_options["region"]``
     - Region of the queue
   * - ``result_backend``
     - ``dynamodb://@<region>/<table>``. Append ``?ttl_seconds=N`` if you want the
       client to configure table TTL too (see :ref:`result-expiration`).
   * - ``task_default_queue``
     - Name of the queue
   * - ``@app.task(name=...)``
     - Always set it explicitly: it must equal the key used in ``TASKS``.
   * - ``task_serializer``, ``result_serializer``, ``accept_content``
     - ``json`` (default), ``msgpack`` or ``yaml``. ``pickle`` is rejected (the task
       is stored as ``FAILURE``: "Unsupported content type"). The runner must use the
       same ``RESULT_SERIALIZER``.
   * - ``task_compression``
     - ``gzip``, ``bzip2`` or ``lzma``. Result compression is not supported.
