IAM roles and permissions
=========================

Two identities need permissions: the **runner** (its Lambda execution role) and the
**client** (whatever identity your application runs as).

Runner execution role
---------------------

.. list-table::
   :header-rows: 1
   :widths: 22 38 40

   * - Service
     - Actions
     - Why
   * - SQS (the queue)
     - ``sqs:ReceiveMessage``, ``sqs:DeleteMessage``, ``sqs:GetQueueAttributes``
     - Read the messages. The managed policy ``AWSLambdaSQSQueueExecutionRole``
       includes them, and CloudWatch Logs.
   * - SQS (the queue)
     - ``sqs:SendMessage``
     - Hold a task until its ``eta``, retries, and the next tasks of a workflow
       (callbacks, chains, chords). Needed on the queue of the event source mapping and
       on any queue named in ``options.queue``
   * - DynamoDB (the table)
     - ``dynamodb:PutItem``, ``dynamodb:GetItem``, ``dynamodb:UpdateItem``,
       ``dynamodb:DeleteItem``
     - Register the task and store its state and result. ``DeleteItem``: forget a task
       rejected with ``requeue`` and clean up finished chords
   * - Lambda (each remote function)
     - ``lambda:InvokeFunction``
     - Only for ``lambda://`` tasks

Create the role
~~~~~~~~~~~~~~~

.. code-block:: bash

   cat > trust-policy.json <<'JSON'
   {
     "Version": "2012-10-17",
     "Statement": [{
       "Effect": "Allow",
       "Principal": {"Service": "lambda.amazonaws.com"},
       "Action": "sts:AssumeRole"
     }]
   }
   JSON

   aws iam create-role --role-name $FUNCTION \
     --assume-role-policy-document file://trust-policy.json

   aws iam attach-role-policy --role-name $FUNCTION \
     --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaSQSQueueExecutionRole

Add the table (and, if you use remote tasks, the functions) as an inline policy:

.. code-block:: bash

   cat > runner-policy.json <<JSON
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Effect": "Allow",
         "Action": [
           "dynamodb:PutItem", "dynamodb:GetItem",
           "dynamodb:UpdateItem", "dynamodb:DeleteItem"
         ],
         "Resource": "arn:aws:dynamodb:$AWS_REGION:$ACCOUNT_ID:table/$TABLE"
       },
       {
         "Effect": "Allow",
         "Action": "sqs:SendMessage",
         "Resource": "$QUEUE_ARN"
       },
       {
         "Effect": "Allow",
         "Action": "lambda:InvokeFunction",
         "Resource": "arn:aws:lambda:$AWS_REGION:$ACCOUNT_ID:function:remote-sum"
       }
     ]
   }
   JSON

   aws iam put-role-policy --role-name $FUNCTION \
     --policy-name runner-access --policy-document file://runner-policy.json

Drop the second statement if you only use local tasks. If your **local tasks**
call other AWS services (S3, Secrets Manager...), add their permissions here too:
they run with the runner's role.

Client permissions
------------------

.. list-table::
   :header-rows: 1
   :widths: 22 38 40

   * - Service
     - Actions
     - Why
   * - SQS (the queue)
     - ``sqs:SendMessage``
     - Send tasks
   * - DynamoDB (the table)
     - ``dynamodb:GetItem``, ``dynamodb:DescribeTable``
     - Read results. Celery's DynamoDB backend checks the table when it starts.

If the client also uses ``celery_cloud.client.install`` to revoke tasks
(:doc:`../user-guide/client-revoke`), it needs ``dynamodb:PutItem`` and
``dynamodb:UpdateItem`` on the table.

If you add ``?ttl_seconds=...`` to the ``result_backend`` URL, Celery also checks
and configures the table's TTL, which needs ``dynamodb:DescribeTimeToLive`` and
``dynamodb:UpdateTimeToLive``.

.. code-block:: json

   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Effect": "Allow",
         "Action": "sqs:SendMessage",
         "Resource": "arn:aws:sqs:eu-central-1:123456789012:lambda-runner-queue"
       },
       {
         "Effect": "Allow",
         "Action": ["dynamodb:GetItem", "dynamodb:DescribeTable"],
         "Resource": "arn:aws:dynamodb:eu-central-1:123456789012:table/lambda-runner-tasks"
       }
     ]
   }

Least privilege
---------------

* Scope every ``Resource`` to the exact ARN, as above.
* Keep the client and the runner on **different** identities: a client does not
  need to write results and the runner does not need to send tasks.
* The ``TASKS`` allowlist already prevents a message from choosing what runs, but
  anyone who can send to the queue can run any task you listed: restrict
  ``sqs:SendMessage`` to the applications that should be able to.
