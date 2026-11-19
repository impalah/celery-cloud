Server: remote Lambda tasks
===========================

A *remote task* runs in **another** Lambda function that you already have (or want
to deploy and version separately). The runner invokes it synchronously. Use it
when the task needs different dependencies, memory, timeout or permissions than the
runner, or when the code belongs to another team.

The contract of the remote function
-----------------------------------

* The runner sends the event ``{"args": [...], "kwargs": {...}}``.
* If the function returns a JSON object with a ``body`` key, ``body`` is the result
  of the task **as it is**: it is not decoded, so return a number or an object, not
  a JSON string (``json.dumps(53)`` would reach the client as the string ``"53"``).
  Otherwise the whole returned value is the
  result.
* If the function raises, Lambda reports a *function error*: the task is stored as
  ``FAILURE`` and it is **not** retried, because the function already ran.

.. literalinclude:: ../examples/remote/handler.py
   :language: python
   :caption: handler.py of the remote function ``remote-sum``

Deploy the remote function
--------------------------

Any Lambda packaging works (zip or image). With a zip:

.. code-block:: bash

   zip function.zip handler.py
   aws lambda create-function --function-name remote-sum --region eu-central-1 \
     --runtime python3.12 --handler handler.lambda_handler \
     --role arn:aws:iam::123456789012:role/remote-sum-role \
     --zip-file fileb://function.zip

The role of ``remote-sum`` only needs the basic execution permissions
(``AWSLambdaBasicExecutionRole``).

Route and permissions
---------------------

Point the task name to the function ARN in ``TASKS``:

.. code-block:: json

   {"remote.sum": "lambda://arn:aws:lambda:eu-central-1:123456789012:function:remote-sum"}

and allow the **runner role** to invoke it (see :doc:`../infrastructure/iam-roles`):

.. code-block:: json

   {
     "Effect": "Allow",
     "Action": "lambda:InvokeFunction",
     "Resource": "arn:aws:lambda:eu-central-1:123456789012:function:remote-sum"
   }

Timeouts and retries
--------------------

* **A remote function can run at most 15 minutes** (the Lambda limit), and the runner
  waits for it, so the **runner's own timeout** (also 900 s at most) must be larger
  than the remote function's. A remote task therefore has less than 15 minutes in
  practice; see :ref:`the execution time limit <execution-time-limit>`.
* ``LAMBDA_INVOKE_TIMEOUT`` (default 840 s) is how long the runner waits for the
  answer. Keep it below the runner's timeout so a slow remote function is recorded
  as ``FAILURE`` instead of the runner being killed: if you set the runner's timeout
  below 840 s, lower this value too.
* Invocation problems (throttling, network) are retried up to ``MAX_ATTEMPTS``
  times.
* After ``CB_FAIL_MAX`` consecutive invocation failures the circuit of that
  function opens for ``CB_RESET_TIMEOUT`` seconds and calls fail fast, so one
  broken function does not consume the whole runner.

The client side of this example is a normal task declaration (see
:doc:`client-basic`); nothing on the client shows that the task is remote:

.. literalinclude:: ../examples/client/remote.py
   :language: python
   :caption: remote.py
