Periodic tasks (replacing celery beat)
======================================

``celery beat`` is a process that sends tasks on a schedule. There is no such process
here, and the schedule belongs to AWS: **Amazon EventBridge Scheduler** sends a message
to the queue on a ``cron`` or ``rate`` expression, and the runner treats it like any
other task.

.. note::

   The Terraform module ``infra/terraform/modules/schedules`` creates all of this (group,
   role, dead-letter queue and the schedules with their message): see
   :ref:`terraform-schedules` below. The Terraform module and the de-duplication behaviour
   below were checked on a real account; the manual ``aws iam`` and ``aws scheduler`` commands were run too.

The message
-----------

The queue receives what a Celery client would send: ``base64(json(envelope))``. Build
it once with the helper the runner uses for its own messages:

.. code-block:: python

   from celery_cloud.messaging import build_message

   task_id, body = build_message(
       {
           "task": "calculator.add",
           "args": [1, 2],
           "kwargs": {},
           "options": {"ignore_result": True},
       },
       queue="lambda-runner-queue",
   )
   print(body)   # the Input of the schedule

Results of every run
--------------------

The runner de-duplicates by **task id**, and a schedule sends the *same* message every
time, so the id is repeated. Two ways to deal with it:

* **Send the task with** ``ignore_result: True`` (as above). A task whose result is
  ignored is not registered in the backend, so it is never taken as a duplicate: every
  message runs. This is the usual case for periodic jobs, and it is the way verified
  by the tests of this project.
* If you need a result per run, the id must change in every run. EventBridge Scheduler
  can put context attributes in the input (for example ``<aws.scheduler.execution-id>``),
  but a base64 body cannot hold a placeholder, so this needs a small function of your own
  that builds the message (``build_message`` above) on every invocation. Using Scheduler
  with a Lambda target and that function is the robust option.

.. _terraform-schedules:

Create the schedules with Terraform
-----------------------------------

The ``schedules`` variable of ``stacks/example`` (module ``modules/schedules``) takes
the equivalent of ``beat_schedule``; the module builds the message, the role the
scheduler assumes (it can only ``sqs:SendMessage`` to the queue) and a dead-letter queue:

.. code-block:: hcl

   schedules = {
     nightly-report = {
       task       = "reports.summarize"
       expression = "cron(0 3 * * ? *)"
       timezone   = "Europe/Madrid"
       args       = [1, 2]
     }
   }

With no entries nothing is created. Create one by hand instead:

.. code-block:: bash

   # the role EventBridge Scheduler assumes, allowed only to send to the queue
   aws iam create-role --role-name scheduler-sqs --assume-role-policy-document '{
     "Version": "2012-10-17",
     "Statement": [{"Effect": "Allow",
       "Principal": {"Service": "scheduler.amazonaws.com"},
       "Action": "sts:AssumeRole",
       "Condition": {"StringEquals": {"aws:SourceAccount": "'$ACCOUNT_ID'"}}}]}'
   aws iam put-role-policy --role-name scheduler-sqs --policy-name send-tasks \
     --policy-document '{"Version": "2012-10-17", "Statement": [{"Effect": "Allow",
       "Action": "sqs:SendMessage", "Resource": "'$QUEUE_ARN'"}]}'

   # a new role can need a few seconds before the scheduler accepts it

   aws scheduler create-schedule --name nightly-report --region $AWS_REGION \
     --schedule-expression "cron(0 3 * * ? *)" \
     --schedule-expression-timezone "Europe/Madrid" \
     --flexible-time-window Mode=OFF \
     --target "{\"Arn\": \"$QUEUE_ARN\", \"RoleArn\": \"arn:aws:iam::$ACCOUNT_ID:role/scheduler-sqs\", \"Input\": \"$BODY\"}"

``$BODY`` is the string printed by ``build_message``.

.. warning::

   Do not add an ``aws:SourceArn`` condition to the trust policy of the role: EventBridge
   Scheduler then refuses to create the schedule ("the execution role you provide must
   allow AWS EventBridge Scheduler to assume the role"). ``aws:SourceAccount`` is enough.

From ``crontab`` to EventBridge
-------------------------------

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - Celery beat
     - EventBridge Scheduler
   * - ``timedelta(minutes=5)``
     - ``rate(5 minutes)``
   * - ``crontab(minute=0, hour=3)``
     - ``cron(0 3 * * ? *)``
   * - ``crontab(minute='*/15')``
     - ``cron(0/15 * * * ? *)``
   * - ``crontab(day_of_week='mon', hour=8)``
     - ``cron(0 8 ? * MON *)``
   * - ``crontab(day_of_month=1, hour=0)``
     - ``cron(0 0 1 * ? *)``
   * - the app's ``timezone``
     - ``--schedule-expression-timezone`` (explicit; Celery uses UTC by default)
   * - ``solar()``, ``nowfun``, ``schedule(run_every=...)`` with sub-minute intervals
     - no equivalent
   * - ``beat_schedule`` in code, ``django-celery-beat``
     - infrastructure as code (Terraform, CloudFormation...) next to the queue

EventBridge cron has six fields (``minutes hours day-of-month month day-of-week year``)
and needs a ``?`` in either day-of-month or day-of-week.

Operations
----------

* Give the schedule a **dead-letter queue** and retry policy for the case that SQS cannot
  be reached.
* ``expires`` in the options of the message makes a late task (for example after an
  outage) be discarded instead of run.
* A task that must not overlap with its previous run should check for it itself: the
  runner will start one every time the schedule fires.
