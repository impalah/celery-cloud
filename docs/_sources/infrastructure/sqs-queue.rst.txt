SQS queue
=========

The queue is the Celery **broker**. The client writes messages to it and the
runner's event source mapping reads them.

Create the queue and a dead-letter queue
----------------------------------------

A dead-letter queue (DLQ) keeps the messages that SQS could not hand over to the
runner after several attempts, so you can inspect them instead of losing them.

.. code-block:: bash

   aws sqs create-queue --queue-name ${QUEUE}-dlq --region $AWS_REGION

   DLQ_ARN=$(aws sqs get-queue-attributes --region $AWS_REGION \
     --queue-url https://sqs.$AWS_REGION.amazonaws.com/$ACCOUNT_ID/${QUEUE}-dlq \
     --attribute-names QueueArn --query Attributes.QueueArn --output text)

Write the attributes of the main queue to a file (the redrive policy is JSON inside
JSON):

.. code-block:: bash

   cat > queue-attributes.json <<JSON
   {
     "VisibilityTimeout": "360",
     "MessageRetentionPeriod": "345600",
     "RedrivePolicy": "{\"deadLetterTargetArn\":\"$DLQ_ARN\",\"maxReceiveCount\":\"5\"}"
   }
   JSON

   aws sqs create-queue --queue-name $QUEUE --region $AWS_REGION \
     --attributes file://queue-attributes.json

Take note of the **queue URL** (``https://sqs.<region>.amazonaws.com/<account>/<queue>``):
the client needs it, and the event source mapping needs the queue **ARN**:

.. code-block:: bash

   QUEUE_URL=https://sqs.$AWS_REGION.amazonaws.com/$ACCOUNT_ID/$QUEUE
   QUEUE_ARN=$(aws sqs get-queue-attributes --region $AWS_REGION --queue-url $QUEUE_URL \
     --attribute-names QueueArn --query Attributes.QueueArn --output text)

Settings that matter
--------------------

.. list-table::
   :header-rows: 1
   :widths: 25 20 55

   * - Attribute
     - Suggested
     - Why
   * - ``VisibilityTimeout``
     - At least **the function timeout** (AWS recommends six times it)
     - While the runner processes a message SQS hides it; if the visibility timeout
       is shorter than the processing time the message is delivered again while it
       is still running. The runner discards that duplicate, but the batch is
       wasted work. With a function timeout of 300 s, 360 s is the minimum and 1800
       s is comfortable.
   * - ``MessageRetentionPeriod``
     - 4 days (default)
     - How long an unprocessed message survives. Keep ``RESULT_TTL_SECONDS`` longer
       than this (see :ref:`result-expiration`).
   * - ``RedrivePolicy.maxReceiveCount``
     - 3 to 5
     - Receives before a message goes to the DLQ. Application failures never
       cause a redelivery; only backend failures (see
       :doc:`../concepts`) and crashes do.

.. warning::

   A **FIFO** queue is not supported: Celery's SQS transport uses standard queues.

Check
-----

.. code-block:: bash

   aws sqs send-message --region $AWS_REGION --queue-url $QUEUE_URL --message-body test
   aws sqs receive-message --region $AWS_REGION --queue-url $QUEUE_URL
   aws sqs purge-queue --region $AWS_REGION --queue-url $QUEUE_URL   # remove the test message

Do this **before** connecting the runner: otherwise the test message will reach it
and fail to decode.
