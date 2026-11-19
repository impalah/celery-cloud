Lambda function and event source
================================

This step creates the runner and connects the queue to it.

Create the function
-------------------

The settings go in an ``env.json`` file, which avoids shell-quoting the ``TASKS``
JSON (see :doc:`../configuration`):

.. literalinclude:: ../examples/server/env.json
   :language: json
   :caption: env.json

.. code-block:: bash

   aws lambda create-function --function-name $FUNCTION --region $AWS_REGION \
     --package-type Image \
     --code ImageUri=$ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/celery-cloud-runner:1 \
     --role arn:aws:iam::$ACCOUNT_ID:role/$FUNCTION \
     --timeout 300 --memory-size 512 \
     --environment file://env.json

.. note::

   A role created seconds ago may not be usable yet; if ``create-function`` says it
   cannot assume the role, wait a few seconds and retry.

Sizing
~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - Setting
     - Guidance
   * - ``--timeout``
     - The longest task you expect, plus margin (**maximum 900 s = 15 minutes**,
       the AWS limit: no task can run longer, see :ref:`execution-time-limit`). If you use
       ``lambda://`` tasks it must exceed the remote function's timeout. The queue's
       visibility timeout must be at least this value.
   * - ``--memory-size``
     - Start at 512 MB and adjust from the ``Max Memory Used`` value of the logs.
       CPU grows with memory.
   * - Concurrency
     - Each concurrent invocation handles one batch. Cap it with
       ``--reserved-concurrent-executions`` (or the ``ScalingConfig`` of the event
       source mapping) to protect downstream systems.

Connect the queue
-----------------

.. code-block:: bash

   aws lambda create-event-source-mapping --region $AWS_REGION \
     --function-name $FUNCTION \
     --event-source-arn $QUEUE_ARN \
     --batch-size 10 \
     --function-response-types ReportBatchItemFailures

``ReportBatchItemFailures`` is **required**: it lets the runner ask SQS to redeliver
only the messages whose state it could not record (see
:ref:`result-expiration` and :doc:`../concepts`). Without it, messages of a batch
that did not raise are deleted whatever happened.

Optional tuning of the mapping:

* ``--maximum-batching-window-in-seconds 5``: wait up to 5 s to fill a batch (fewer
  invocations, more latency).
* ``--scaling-config MaximumConcurrency=10``: limit how many invocations run at
  once.

Update the function
-------------------

.. code-block:: bash

   # new code (a new image tag)
   aws lambda update-function-code --function-name $FUNCTION --region $AWS_REGION \
     --image-uri $ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/celery-cloud-runner:2

   # new settings (this REPLACES all the variables: send them all)
   aws lambda update-function-configuration --function-name $FUNCTION \
     --region $AWS_REGION --environment file://env.json

Smoke test
----------

Send one task with a client (:doc:`../user-guide/client-basic`) and follow the logs:

.. code-block:: bash

   aws logs tail /aws/lambda/$FUNCTION --follow --region $AWS_REGION

You should see the invocation with its ``trace_id``, and the client prints the
result.
