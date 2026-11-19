# ecr-repository

The ECR repository of the runner image (scan on push, immutable tags, lifecycle policy). Lambda only runs images stored in ECR in the same account and Region as the function.

Inputs: `name` (required), `image_tag_mutability` (`IMMUTABLE`), `keep_images` (`20`), `force_delete` (`false`), `tags`. Outputs: `repository_url`, `repository_arn`, `repository_name`.
