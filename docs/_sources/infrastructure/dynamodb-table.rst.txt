DynamoDB table
==============

The table is the Celery **result backend**. The runner writes the state and result
of each task; the client reads them with ``AsyncResult``.

Create the table
----------------

.. code-block:: bash

   aws dynamodb create-table --table-name $TABLE --region $AWS_REGION \
     --attribute-definitions AttributeName=id,AttributeType=S \
     --key-schema AttributeName=id,KeyType=HASH \
     --billing-mode PAY_PER_REQUEST

.. important::

   The table must have a **single string hash key named** ``id`` and **no sort
   key**. Both the Celery client and the runner use exactly that layout. Any other
   schema makes reads and writes fail.

On-demand billing (``PAY_PER_REQUEST``) fits this workload: you pay per task and
nothing while idle, which is the point of a serverless runner. The client URL
``dynamodb://@region/table?read=5&write=5`` only matters if the *client* creates
the table; with an existing table those values are ignored.

Enable automatic expiration (recommended)
-----------------------------------------

Without a TTL the table grows forever. The runner writes the ``ttl`` attribute
(see :ref:`result-expiration`), but DynamoDB only deletes expired items when TTL is
enabled for that attribute:

.. code-block:: bash

   aws dynamodb update-time-to-live --table-name $TABLE --region $AWS_REGION \
     --time-to-live-specification Enabled=true,AttributeName=ttl

Choose the retention with ``RESULT_TTL_SECONDS`` on the function (default 24 h).
Deletion is not instantaneous: expired items can remain visible for a while.

Check
-----

.. code-block:: bash

   aws dynamodb describe-table --table-name $TABLE --region $AWS_REGION \
     --query "Table.[TableStatus,KeySchema,BillingModeSummary.BillingMode]"
   aws dynamodb describe-time-to-live --table-name $TABLE --region $AWS_REGION

After the first task you can inspect what the runner wrote:

.. code-block:: bash

   aws dynamodb scan --table-name $TABLE --region $AWS_REGION --max-items 3

Items look like this (the ``result`` binary is the JSON of
:ref:`backend-item-format`):

.. code-block:: json

   {
     "id": {"S": "b'celery-task-meta-8d58fa0a-f181-47ff-83e9-9ddfd2ee8af9'"},
     "result": {"B": "..."},
     "timestamp": {"N": "1767261600"},
     "ttl": {"N": "1767348000"}
   }

Several environments
--------------------

Use **one table per environment** (or at least per application) and point the
``result_backend`` of that application and ``CELERY_BACKEND_TABLE`` of its runner to
it. Several queues can share one table because task ids are unique, but separating
them keeps permissions and expiration simple.
