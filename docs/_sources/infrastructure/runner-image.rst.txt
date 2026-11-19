Runner image (ECR)
==================

The runner is deployed as a **container image**. AWS Lambda runs images that are
stored in an **Amazon ECR repository in the same Region as the function**, so you
push the image to your own repository.

The base image
--------------

A published base image contains ``celery-cloud`` and the Lambda handler:

.. code-block:: text

   public.ecr.aws/e2b2x4l7/celery-cloud/lambda-runner

Browse the existing tags at https://gallery.ecr.aws/e2b2x4l7/celery-cloud/lambda-runner.
There is **no** ``latest`` tag, and published tags can be older than the version on
PyPI: check that the tag you use contains the behaviour described here. If in doubt,
build your own image from the repository (``Dockerfile`` at its root).

Create your repository
----------------------

.. code-block:: bash

   aws ecr create-repository --repository-name celery-cloud-runner --region $AWS_REGION

   aws ecr get-login-password --region $AWS_REGION \
     | docker login --username AWS --password-stdin \
       $ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com

Image with remote tasks only
----------------------------

If every task is ``lambda://``, no code of yours is needed in the runner: pull the
base image, tag it and push it.

.. code-block:: bash

   docker pull --platform linux/amd64 public.ecr.aws/e2b2x4l7/celery-cloud/lambda-runner:<tag>
   docker tag public.ecr.aws/e2b2x4l7/celery-cloud/lambda-runner:<tag> \
     $ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/celery-cloud-runner:1
   docker push $ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/celery-cloud-runner:1

Image with local tasks
----------------------

Build on top of the base image (see :doc:`../user-guide/server-local-tasks` for the
complete ``Dockerfile``):

.. code-block:: dockerfile

   FROM public.ecr.aws/e2b2x4l7/celery-cloud/lambda-runner:<tag>
   COPY calculator.py reports.py ${LAMBDA_TASK_ROOT}/

.. code-block:: bash

   docker build --platform linux/amd64 --provenance=false \
     -t $ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/celery-cloud-runner:1 .
   docker push $ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/celery-cloud-runner:1

* ``--platform`` must match the architecture of the function (``linux/amd64`` for
  ``x86_64``; use ``linux/arm64`` together with ``--architectures arm64``).
* ``--provenance=false`` avoids the extra attestation manifest that Lambda does not
  accept.

Build the base image yourself
-----------------------------

The repository ``Dockerfile`` installs ``celery-cloud`` and its dependencies
(through ``uv``) and sets the handler:

.. code-block:: bash

   git clone https://github.com/impalah/celery-cloud.git && cd celery-cloud
   docker build --platform linux/amd64 --provenance=false \
     -t $ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/celery-cloud-runner:base .

Test the image locally
----------------------

The AWS base image includes the Lambda Runtime Interface Emulator:

.. code-block:: bash

   docker run --rm -p 9000:8080 \
     -e TASKS='{"calculator.add": "task://calculator/add"}' \
     -e CELERY_BACKEND_TABLE=$TABLE -e CELERY_BACKEND_REGION=$AWS_REGION \
     -e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY -e AWS_SESSION_TOKEN \
     $ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/celery-cloud-runner:1

   curl -X POST http://localhost:9000/2015-03-31/functions/function/invocations \
     -d @sqs_event.json

Versioning
----------

Use immutable tags (``1``, ``2``, ``2025-01-15``...) and update the function to the
new tag; do not overwrite a tag that a function uses, because Lambda resolves the
tag to a digest at deploy time.
