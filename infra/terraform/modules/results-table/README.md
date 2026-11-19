# results-table

The Celery result backend: an on-demand DynamoDB table with a single string hash key `id` and TTL on the attribute `ttl`. That layout is what Celery's DynamoDB backend and the runner both expect; do not change it.

Inputs: `name` (required), `point_in_time_recovery` (`false`), `deletion_protection` (`false`), `tags`. Outputs: `table_name`, `table_arn`.
