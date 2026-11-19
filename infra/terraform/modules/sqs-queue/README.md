# sqs-queue

The Celery broker: a standard SQS queue with a dead-letter queue, both encrypted with the SQS-managed key.

| Input | Meaning | Default |
| --- | --- | --- |
| `name` | Queue name (the dead-letter queue is `<name>-dlq`) | required |
| `visibility_timeout_seconds` | Must be at least the timeout of the function that reads it | `1800` |
| `message_retention_seconds` | How long an unprocessed message lives | `345600` (4 days) |
| `max_receive_count` | Receives before the dead-letter queue | `5` |

Outputs: `queue_name`, `queue_url`, `queue_arn`, `dlq_arn`, `dlq_url`.
