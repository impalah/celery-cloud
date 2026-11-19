User Guide
==========

Complete, runnable examples for both sides of Celery Cloud. The code of every
example is a real file in ``pages_source/examples/`` of the repository; the server
examples are exercised by the test suite.

The examples share one scenario: a small calculator and a text report, written as
**local tasks** (packaged with the runner) plus one **remote task** (an existing
Lambda function).

.. list-table::
   :header-rows: 1
   :widths: 20 40 40

   * - Task name
     - Where it runs
     - Used in
   * - ``calculator.add``
     - ``task://calculator/add``
     - :doc:`user-guide/client-basic`
   * - ``calculator.subtract`` / ``calculator.divide``
     - ``task://calculator/...``
     - :doc:`user-guide/client-errors`
   * - ``reports.summarize``
     - ``task://reports/summarize``
     - :doc:`user-guide/client-structured`
   * - ``remote.sum``
     - ``lambda://<arn>``
     - :doc:`user-guide/server-remote-lambda`
   * - ``jobs.*`` (retries, progress, limits)
     - ``task://jobs/...`` (decorated with ``@task``)
     - :doc:`user-guide/server-task-api`, :doc:`user-guide/client-retries-progress`
   * - ``calculator.total``, ``calculator.report_error``
     - ``task://calculator/...``
     - :doc:`user-guide/client-canvas`

.. toctree::
   :maxdepth: 1
   :caption: Server side (the runner)

   user-guide/server-local-tasks
   user-guide/server-task-api
   user-guide/server-remote-lambda
   user-guide/server-local-debugging

.. toctree::
   :maxdepth: 1
   :caption: Client side (your application)

   user-guide/client-basic
   user-guide/client-errors
   user-guide/client-structured
   user-guide/client-retries-progress
   user-guide/client-canvas
   user-guide/client-revoke
