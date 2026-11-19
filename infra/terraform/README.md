# Infrastructure (Terraform)

The AWS resources that Celery Cloud needs, as code: an SQS queue with a dead-letter queue (the broker), a DynamoDB table (the result backend), an ECR repository, the runner Lambda function with its event source mapping, and the IAM policy of the client. The step-by-step version with the AWS CLI is in the documentation (`pages_source/infrastructure/`); this is the same thing as Terraform.

**Nothing is applied to AWS without reviewing the `plan` first.** Every resource is named `<project>-<environment>-...` and tagged `project`, `environment`, `owner` and `managed-by`.

> Status: validated without credentials (`check.sh`) **and applied once against a real AWS account** (2026-11-19, `eu-central-1`, environment `test`): 12 resources in two applies, the user-guide client examples ran against it (see `documentation/07-registro-paridad.md`). Read the plan before applying anyway.

## Layout

| Folder | What it holds |
| --- | --- |
| `modules/` | Generic modules, no project values: `sqs-queue`, `results-table`, `ecr-repository`, `lambda-runner`, `schedules` (EventBridge Scheduler). Each one has `main.tf`, `variables.tf`, `outputs.tf`, `versions.tf` and a `README.md` |
| `stacks/example/` | A complete environment built from the modules. Another environment (`staging`...) is the same code with another `environment` and another state key, not a copy of the folder |

State and versions: remote state in an S3 bucket that **you already own** (`application.backend.conf`), locked with `use_lockfile` (Terraform >= 1.10, no DynamoDB table). Terraform `>= 1.10, < 2`, provider `hashicorp/aws ~> 6.0`. The provider refuses any account other than `aws_account_id`. No secrets live in the code; no IAM access key is created (it would be stored in the state).

## Use

```bash
cd stacks/example
cp application.backend.conf.template application.backend.conf               # edit: your state bucket
cp application.configuration.tfvars.template application.configuration.tfvars   # edit
export AWS_PROFILE=...                      # never in Git

terraform init -backend-config=application.backend.conf
terraform plan -var-file=application.configuration.tfvars -out=plan.tfplan
# review the plan; only then:
terraform apply plan.tfplan
```

### The image comes between two applies

The function runs a container image, and the image has to be in the repository before the function can be created. So the first `apply` leaves `runner_image_tag` empty and creates the queue, the table, the repository and the client policy; then:

```bash
REPO=$(terraform output -raw repository_url)
REGION=eu-central-1

aws ecr get-login-password --region $REGION | docker login --username AWS --password-stdin ${REPO%%/*}

# an image with the runner AND your tasks (see pages_source/infrastructure/runner-image.rst)
docker build --platform linux/amd64 --provenance=false -t $REPO:1 .
docker push $REPO:1
```

Set `runner_image_tag = "1"` in the tfvars and run `plan` / `apply` again: it creates the function, its role, the log group and the event source mapping. Tags are immutable: a new image is a new tag (`2`, `3`...), followed by an `apply`.

### Try the client

```bash
export CELERY_QUEUE_URL=$(terraform output -raw queue_url)
export CELERY_BACKEND_TABLE=$(terraform output -raw results_table)
export AWS_REGION=eu-central-1
python pages_source/examples/client/basic.py        # from the root of the repository
aws logs tail $(terraform output -raw runner_log_group) --follow
```

Attach `client_policy_arn` to the identity of the application (or set `create_client_user = true` for an IAM user to try from your laptop, and create its access key yourself).

### Clean up

```bash
terraform destroy -var-file=application.configuration.tfvars
```

The repository is deleted even if it holds images (`ecr_force_delete`, true by default in this example stack). Set `table_deletion_protection = true` for anything you want to keep.

## Checks without credentials

`./check.sh` runs `terraform fmt -check -recursive`, then `terraform init -backend=false` and `terraform validate` in every module and in the stack, and `terraform test` (`stacks/example/example.tftest.hcl`: plan-level tests with a **mocked** AWS provider, e.g. no function without an image, the visibility timeout, the timeout limit). It discards any `AWS_*` variable from the environment and needs no state. Also available as `make infra-check`.

The files you create from the templates (`application.backend.conf`, `application.configuration.tfvars`), `.terraform/`, the state and the plans are in `.gitignore`.
