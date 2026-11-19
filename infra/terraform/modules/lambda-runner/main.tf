# The runner: an AWS Lambda container image wired to the SQS queue with an event source mapping.
#
# - `ReportBatchItemFailures` is REQUIRED: it is how the runner asks SQS to redeliver only the
#   messages it could not record (backend failures, Reject(requeue), records it had no time for).
# - The role is least-privilege: exactly this queue, this table and the remote functions listed.

data "aws_iam_policy_document" "assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "this" {
  name               = var.name
  assume_role_policy = data.aws_iam_policy_document.assume.json
  tags               = var.tags
}

# Logs: create the log group ourselves (with retention) and let the role write to it
resource "aws_cloudwatch_log_group" "this" {
  name              = "/aws/lambda/${var.name}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

data "aws_iam_policy_document" "runner" {
  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.this.arn}:*"]
  }

  # Read the messages, and send them back: a task held until its eta, retries, callbacks,
  # chain steps and chord bodies
  statement {
    sid = "Queue"
    actions = [
      "sqs:ReceiveMessage",
      "sqs:DeleteMessage",
      "sqs:GetQueueAttributes",
      "sqs:SendMessage",
    ]
    resources = [var.queue_arn]
  }

  # Register the task and store its state and result; forget a rejected task and clean up chords
  statement {
    sid = "Results"
    actions = [
      "dynamodb:PutItem",
      "dynamodb:GetItem",
      "dynamodb:UpdateItem",
      "dynamodb:DeleteItem",
    ]
    resources = [var.table_arn]
  }

  dynamic "statement" {
    for_each = length(var.remote_function_arns) > 0 ? [1] : []

    content {
      sid       = "RemoteTasks"
      actions   = ["lambda:InvokeFunction"]
      resources = var.remote_function_arns
    }
  }
}

resource "aws_iam_role_policy" "runner" {
  name   = "runner-access"
  role   = aws_iam_role.this.id
  policy = data.aws_iam_policy_document.runner.json
}

resource "aws_lambda_function" "this" {
  function_name = var.name
  role          = aws_iam_role.this.arn
  package_type  = "Image"
  image_uri     = var.image_uri
  architectures = [var.architecture]
  timeout       = var.timeout
  memory_size   = var.memory_size

  environment {
    variables = merge(
      {
        CELERY_BACKEND_TABLE  = var.table_name
        CELERY_BACKEND_REGION = var.region
        TASKS                 = jsonencode(var.tasks)
      },
      var.environment_variables,
    )
  }

  tags = var.tags

  depends_on = [
    aws_cloudwatch_log_group.this,
    aws_iam_role_policy.runner,
  ]
}

resource "aws_lambda_event_source_mapping" "queue" {
  event_source_arn = var.queue_arn
  function_name    = aws_lambda_function.this.arn
  batch_size       = var.batch_size

  function_response_types = ["ReportBatchItemFailures"]

  dynamic "scaling_config" {
    for_each = var.maximum_concurrency == null ? [] : [1]

    content {
      maximum_concurrency = var.maximum_concurrency
    }
  }
}
