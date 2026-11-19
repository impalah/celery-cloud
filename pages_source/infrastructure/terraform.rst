Terraform
=========

Everything in this section can also be created with Terraform. The code is in
``infra/terraform/`` of the repository: four generic modules and a complete example
stack.

.. important::

   The code has been validated without credentials (``terraform validate`` and plan-level
   tests with a mocked provider) and applied once against a real AWS account
   (``eu-central-1``): the queue, table, repository and function were created in two
   applies and the client examples of the user guide ran against it. Read the plan before
   applying it anyway.

What it creates
---------------

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - Module
     - Resources
   * - ``sqs-queue``
     - The queue and its dead-letter queue (encrypted, with the redrive policy)
       (:doc:`sqs-queue`)
   * - ``results-table``
     - The DynamoDB table: on-demand, hash key ``id``, TTL on ``ttl``
       (:doc:`dynamodb-table`)
   * - ``ecr-repository``
     - The repository of the runner image: scan on push, immutable tags, lifecycle policy
       (:doc:`runner-image`)
   * - ``lambda-runner``
     - The function, its least-privilege role, the log group and the event source
       mapping with ``ReportBatchItemFailures`` (:doc:`iam-roles`,
       :doc:`lambda-function`)
   * - ``schedules``
     - Optional periodic tasks: EventBridge Scheduler group and schedules, their role and
       dead-letter queue (:doc:`periodic-tasks`)

The ``stacks/example`` stack puts them together and adds the IAM policy for the client
application (and, optionally, an IAM user to try it from your laptop).

Use
---

.. code-block:: bash

   cd infra/terraform/stacks/example
   cp application.backend.conf.template application.backend.conf               # your state bucket
   cp application.configuration.tfvars.template application.configuration.tfvars   # edit
   export AWS_PROFILE=...

   terraform init -backend-config=application.backend.conf
   terraform plan -var-file=application.configuration.tfvars -out=plan.tfplan
   terraform apply plan.tfplan

The state bucket must already exist: Terraform does not create its own. The provider
refuses any account other than ``aws_account_id``.

The image comes between two applies
-----------------------------------

A Lambda function cannot be created before its image exists in ECR. The first ``apply``
(with ``runner_image_tag = ""``) creates the queue, the table, the repository and the
client policy. Then build and push the image (:doc:`runner-image`):

.. code-block:: bash

   REPO=$(terraform output -raw repository_url)
   aws ecr get-login-password --region eu-central-1 \
     | docker login --username AWS --password-stdin ${REPO%%/*}
   docker build --platform linux/amd64 --provenance=false -t $REPO:1 .
   docker push $REPO:1

Set ``runner_image_tag = "1"`` and apply again: it creates the function and connects the
queue. Tags are immutable, so a new image is a new tag followed by an ``apply``.

Then try the client with the outputs (``queue_url``, ``results_table``,
``runner_log_group``) as in :doc:`../user-guide/client-basic`, and clean up with
``terraform destroy`` when you are done.

Checks
------

``make infra-check`` (or ``infra/terraform/check.sh``) runs ``terraform fmt -check``,
``validate`` in every module and in the stack, and ``terraform test`` with a mocked AWS
provider. It needs no credentials and no state.
