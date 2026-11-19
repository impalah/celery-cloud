# Module `schedules`

Periodic tasks (what `celery beat` does) with **EventBridge Scheduler**: a schedule group, one
schedule per entry of `schedules`, the role the scheduler assumes (it can only `sqs:SendMessage`
to the Celery queue and to this module's dead-letter queue) and that dead-letter queue.

The scheduler's `Input` is the Celery protocol-2 message, built in Terraform (same format as
`celery_cloud.messaging.build_message`). Every run of a schedule carries the same task id, so
tasks are sent with `ignore_result = true` by default (nothing is registered, nothing is
de-duplicated). Expressions use EventBridge syntax (`cron(0 3 * * ? *)`, `rate(5 minutes)`),
not crontab.

See `pages_source/infrastructure/periodic-tasks.rst`.
