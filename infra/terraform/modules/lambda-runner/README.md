# lambda-runner

The runner: a Lambda container image, its least-privilege role (this queue, this table and the remote functions listed), a log group with retention and the event source mapping with `ReportBatchItemFailures`.

| Input | Meaning | Default |
| --- | --- | --- |
| `name`, `image_uri` | Function name and image in ECR | required |
| `queue_arn`, `table_arn`, `table_name`, `region` | Broker and backend | required |
| `tasks` | The `TASKS` setting | `{}` |
| `remote_function_arns` | Functions that `lambda://` tasks may invoke | `[]` |
| `environment_variables` | Other settings (`LOG_LEVEL`, `RESULT_TTL_SECONDS`...) | `{}` |
| `timeout` | 1 to 900 s | `300` |
| `memory_size`, `architecture` | 512 MB, `x86_64` (the image must match) | |
| `batch_size`, `maximum_concurrency` | Mapping tuning | `10`, no limit |

Outputs: `function_name`, `function_arn`, `role_arn`, `log_group_name`.
