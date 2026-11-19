Installation
============

Requirements
------------

* An AWS account with permissions to create an SQS queue, a DynamoDB table, an
  ECR repository, a Lambda function and its IAM role (see :doc:`infrastructure`).
* Python **3.12 or newer** for the runner and for local development.
* For the client application: Celery with the SQS and DynamoDB extras. The
  client does **not** need ``celery-cloud``.

What to install where
---------------------

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - Where
     - What to install
   * - Client application (sends tasks, reads results)
     - ``pip install "celery[sqs,dynamodb]"``
   * - Runner, ready-made container image
     - Nothing: use the published image (see :doc:`infrastructure/runner-image`)
   * - Runner with your own code, or local development
     - ``pip install celery-cloud``

``celery-cloud`` installs the runner library (``boto3``, ``pydantic``,
``pynamodb``, ``loguru``, ``tenacity``, ``pybreaker``...). It **does not install
Celery**, because the runner implements the consumer side by itself.

Install the client
------------------

.. code-block:: bash

   python -m venv .venv
   source .venv/bin/activate
   pip install "celery[sqs,dynamodb]"

or with `uv <https://docs.astral.sh/uv/>`_:

.. code-block:: bash

   uv add "celery[sqs,dynamodb]"

Install the runner library
--------------------------

You need it to run the runner on your machine (tests, debugging) or to build an
image that does not start from the published one:

.. code-block:: bash

   pip install celery-cloud
   # or
   uv add celery-cloud

Check the installation:

.. code-block:: bash

   python -c "import celery_cloud.runners.aws_lambda as r; print(r.lambda_handler)"

Install from source
-------------------

.. code-block:: bash

   git clone https://github.com/impalah/celery-cloud.git
   cd celery-cloud
   uv sync          # runtime + development dependencies
   make check       # lint, types and security scan
   make test        # tests with coverage

Build this documentation
------------------------

.. code-block:: bash

   uv sync --group docs
   make docs          # HTML into docs/
   make docs-serve    # http://localhost:8000

The sources are in ``pages_source/`` and the generated HTML in ``docs/``, which
is what GitHub Pages publishes.

AWS credentials
---------------

Both the client and the runner use the standard AWS credential chain: environment
variables, a shared profile (``AWS_PROFILE``) or an instance/function role. The
runner on Lambda uses its execution role; there is nothing to configure.
