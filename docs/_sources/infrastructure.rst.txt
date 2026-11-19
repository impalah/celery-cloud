.. _infrastructure:

Infrastructure
==============

Celery Cloud needs five AWS pieces. This section explains what each one is for and
how to create it, in the order you should create them.

.. mermaid::

   graph LR
       App["Your application<br/>(Celery client)"]
       Q["SQS queue"]
       DLQ["Dead-letter queue"]
       F["Runner<br/>(Lambda, container image)"]
       T["DynamoDB table"]
       R["Remote Lambda<br/>(optional)"]
       ECR["ECR repository"]

       App -- "SendMessage" --> Q
       Q -- "event source mapping" --> F
       Q -. "after N failed receives" .-> DLQ
       ECR -- "image" --> F
       F -- "PutItem / UpdateItem" --> T
       F -- "InvokeFunction" --> R
       App -- "GetItem" --> T

.. list-table::
   :header-rows: 1
   :widths: 25 45 30

   * - Piece
     - Role
     - Guide
   * - SQS queue (+ dead-letter queue)
     - The Celery broker: where the client leaves the tasks
     - :doc:`infrastructure/sqs-queue`
   * - DynamoDB table
     - The Celery result backend: states and results
     - :doc:`infrastructure/dynamodb-table`
   * - IAM roles
     - Permissions of the runner and of the client
     - :doc:`infrastructure/iam-roles`
   * - ECR repository + image
     - The container image of the runner (your tasks included)
     - :doc:`infrastructure/runner-image`
   * - Lambda function + event source mapping
     - The runner itself, wired to the queue
     - :doc:`infrastructure/lambda-function`

.. toctree::
   :maxdepth: 1

   infrastructure/sqs-queue
   infrastructure/dynamodb-table
   infrastructure/iam-roles
   infrastructure/runner-image
   infrastructure/lambda-function
   infrastructure/terraform
   infrastructure/periodic-tasks
   infrastructure/queues-and-priorities
   infrastructure/operations

Conventions of the guides
-------------------------

The guides use the AWS CLI (v2) and these values; replace them with yours:

.. code-block:: bash

   export AWS_REGION=eu-central-1
   export ACCOUNT_ID=123456789012
   export QUEUE=lambda-runner-queue
   export TABLE=lambda-runner-tasks
   export FUNCTION=celery-cloud-runner

.. note::

   All the pieces must be in the **same Region**: the Lambda image has to be in an
   ECR repository of the Region of the function, and the client, queue and table are
   configured with that Region.

.. tip::

   The same resources are available as Terraform code: see :doc:`infrastructure/terraform`.

.. note::

   The commands follow the AWS documentation but have not been run against a real
   account while writing this guide. Read the output of each step; the tools
   (Terraform, CloudFormation, CDK, SAM) can express exactly the same resources if
   you prefer infrastructure as code.
