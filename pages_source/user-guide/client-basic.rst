Client: sending a task
======================

Your application uses a **plain Celery client**. It declares the tasks (name and
signature), sends them to SQS and reads the result from DynamoDB. It does not need
``celery-cloud``.

.. code-block:: bash

   pip install "celery[sqs,dynamodb]"

Configure the client
--------------------

.. literalinclude:: ../examples/client/celery_app.py
   :language: python
   :caption: celery_app.py

Points that matter:

* ``@app.task(name=...)`` must equal the key of ``TASKS`` in the runner. If you
  leave the name out, Celery derives it from the module (``celery_app.add``), which
  is easy to get wrong.
* The task bodies are never executed on the client: they only document the
  signature.
* The queue must already exist (``predefined_queues``): the client does not
  create it.
* Credentials and region come from the standard AWS mechanisms (environment,
  profile, role). The client needs ``sqs:SendMessage`` on the queue and, on the
  table, ``dynamodb:GetItem`` and ``dynamodb:DescribeTable`` (see
  :doc:`../infrastructure/iam-roles`).

Send and wait
-------------

.. literalinclude:: ../examples/client/basic.py
   :language: python
   :caption: basic.py

.. code-block:: bash

   export CELERY_QUEUE_URL=https://sqs.eu-central-1.amazonaws.com/123456789012/lambda-runner-queue
   export AWS_PROFILE=my-profile
   python basic.py
   # Sent task 8d58fa0a-f181-47ff-83e9-9ddfd2ee8af9
   # Result: 18
   # State:  SUCCESS

``delay``, ``apply_async`` and ``send_task``
--------------------------------------------

All the usual ways to send a task work:

.. code-block:: python

   add.delay(10, 3)                                   # positional shortcut
   add.apply_async(args=(10, 3), kwargs={"extra": 5})  # full control
   app.send_task("calculator.add", args=(10, 3))       # by name, no declaration needed

``send_task`` is useful when the client should not import the task declarations at
all.

Options the runner honours
--------------------------

.. code-block:: python

   # The result is not stored (nothing can be read back, not even failures)
   add.apply_async(args=(1, 2), ignore_result=True)

   # Skip the task (REVOKED) if the runner receives it more than 60 seconds after sending
   add.apply_async(args=(1, 2), expires=60)

``countdown`` and ``eta`` are **not** supported: the task runs as soon as the
message arrives.
