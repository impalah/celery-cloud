Operations
==========

Monitoring
----------

* **Logs**: ``/aws/lambda/<function>`` in CloudWatch Logs. Every line carries the
  ``trace_id`` of its invocation; raise ``LOG_LEVEL`` to ``DEBUG`` temporarily to see
  more. ``LOG_DIAGNOSE=true`` adds local variables to tracebacks and can leak task
  arguments: do not leave it on.
* **Response of every invocation**: the handler returns the counters
  (``processed_messages``, ``failed_messages``, ``skipped_messages``) and the list
  of tasks of each kind.
* **Metrics**: with ``METRICS_ENABLED=true`` the runner writes CloudWatch metrics in the
  Embedded Metric Format (namespace ``CeleryCloud``, dimension ``Task``): ``TaskSucceeded``,
  ``TaskFailed``, ``TaskRetried``, ``TaskSkipped``, ``TaskDelayed``, ``TaskIgnored``,
  ``TaskRejected`` and ``TaskDuration`` (ms). They come from the log line, so they need
  no IAM permission and no API call (CloudWatch Logs ingestion is billed as usual).
* **Alarms worth creating**

  .. list-table::
     :header-rows: 1
     :widths: 40 60

     * - Metric
       - Meaning
     * - SQS ``ApproximateNumberOfMessagesVisible`` of the queue
       - Tasks are waiting: the runner is throttled, failing or too slow
     * - SQS ``ApproximateNumberOfMessagesVisible`` of the **DLQ** (> 0)
       - Messages the runner could not handle after ``maxReceiveCount`` attempts
     * - Lambda ``Errors``, ``Throttles``, ``Duration`` (near the timeout)
       - Crashes, concurrency limits and tasks about to be killed
     * - ``TaskFailed`` / ``TaskRetried`` (with metrics enabled)
       - A task that fails or retries more than usual

Troubleshooting
---------------

.. list-table::
   :header-rows: 1
   :widths: 38 62

   * - Symptom
     - Check
   * - Client waits forever (``PENDING``)
     - Is the event source mapping enabled and pointing to this queue? Is the client
       writing to the same queue and the runner reading the table the client reads
       (same table and Region)?
   * - ``FAILURE``: task not found / not allowed
     - The ``@app.task(name=...)`` of the client does not match a key of ``TASKS``.
   * - ``FAILURE``: "Unsupported content type"
     - The client is not using the ``json`` serializer.
   * - Stuck in ``STARTED``
     - The runner died or timed out mid-task. Increase the timeout or fix the task;
       the client must have a timeout (see :doc:`../concepts`).
   * - Task runs twice
     - Visibility timeout shorter than the function timeout, or the result item was
       already deleted by TTL (see :ref:`result-expiration`). Without
       ``ReportBatchItemFailures`` backend failures are not retried.
   * - ``AccessDenied`` in the logs
     - Missing permission in the runner role (:doc:`iam-roles`).
   * - Messages go to the DLQ
     - Read them (``aws sqs receive-message`` on the DLQ), fix the cause and move
       them back with the redrive button of the SQS console.

Costs
-----

You pay per request and per millisecond, and nothing while the queue is empty:
Lambda invocations (duration x memory), SQS requests, DynamoDB on-demand reads and
writes (a task writes its item twice or three times: ``STARTED`` and the final
state), ECR storage and CloudWatch Logs. Set a retention period on the log group
(``aws logs put-retention-policy``) so logs do not accumulate indefinitely.

Cleanup
-------

.. code-block:: bash

   aws lambda delete-event-source-mapping --uuid <mapping-uuid> --region $AWS_REGION
   aws lambda delete-function --function-name $FUNCTION --region $AWS_REGION
   aws ecr delete-repository --repository-name celery-cloud-runner --force --region $AWS_REGION
   aws dynamodb delete-table --table-name $TABLE --region $AWS_REGION
   aws sqs delete-queue --queue-url $QUEUE_URL --region $AWS_REGION
   aws sqs delete-queue --queue-url ${QUEUE_URL}-dlq --region $AWS_REGION
   aws iam delete-role-policy --role-name $FUNCTION --policy-name runner-access
   aws iam detach-role-policy --role-name $FUNCTION \
     --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaSQSQueueExecutionRole
   aws iam delete-role --role-name $FUNCTION

``delete-table`` and ``delete-queue`` destroy data and cannot be undone.
