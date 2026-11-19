Several queues, priorities and rate limits
==========================================

Celery routes tasks to queues and workers consume the queues they choose. Here the
equivalent is built from AWS resources, with no extra code.

One queue per event source mapping
----------------------------------

Create one SQS queue per kind of work and connect each to a function with its own event
source mapping (:doc:`lambda-function`). The same function can have several mappings, or
you can deploy one function per queue with different ``TASKS``, memory, timeout and
concurrency.

On the client, send the task to a queue with Celery's routing:

.. code-block:: python

   app.conf.task_routes = {"reports.*": {"queue": "reports"}}
   app.conf.broker_transport_options["predefined_queues"] = {
       "lambda-runner-queue": {"url": QUEUE_URL},
       "reports": {"url": REPORTS_QUEUE_URL},
   }

``options.queue`` of a callback or chain step goes to that queue too (in the same account
and Region as the queue the task came from).

Priorities
----------

SQS has no priorities inside a queue. Use **separate queues** (``high``, ``default``,
``low``) and give each mapping its own concurrency: the high queue gets a larger
``MaximumConcurrency`` (or its own function with reserved concurrency).

Rate limits
-----------

Celery's ``rate_limit`` is per worker and is not implemented. Limit the load with AWS:

* ``--scaling-config MaximumConcurrency=N`` on the event source mapping: at most ``N``
  invocations at the same time (2 to 1000).
* ``--reserved-concurrent-executions N`` on the function.
* ``--batch-size`` and ``--maximum-batching-window-in-seconds``.
* For a limit **per second** against an external API, put the limiter in the task (for
  example a counter in DynamoDB or an API gateway quota) and use ``self.retry`` with a
  countdown when the limit is reached.

Time and cost
-------------

Each queue keeps its own dead-letter queue and visibility timeout; set the visibility
timeout of every queue to at least the timeout of the function that reads it
(:doc:`sqs-queue`).
