# Periodic tasks (celery beat's job) with EventBridge Scheduler: on every cron/rate tick the
# scheduler puts a Celery protocol-2 message in the queue (the format celery_cloud.messaging
# builds), and the runner treats it like any other task. Nothing runs between ticks.

data "aws_caller_identity" "current" {}

locals {
  # The message of every schedule: base64(json(envelope)), the format kombu writes to SQS.
  # The task id is derived from the schedule name, so it is stable across applies.
  messages = {
    for key, s in var.schedules : key => {
      task_id = uuidv5("url", "${var.name}/${key}")
    }
  }

  bodies = {
    for key, s in var.schedules : key => base64encode(jsonencode({
      "body"             = base64encode(jsonencode([s.args, s.kwargs, { callbacks = null, errbacks = null, chain = null, chord = null }]))
      "content-encoding" = "utf-8"
      "content-type"     = "application/json"
      "headers" = {
        lang                  = "py"
        task                  = s.task
        id                    = local.messages[key].task_id
        shadow                = null
        eta                   = null
        expires               = null
        group                 = null
        group_index           = null
        retries               = 0
        timelimit             = [s.time_limit, s.soft_time_limit]
        root_id               = local.messages[key].task_id
        parent_id             = null
        argsrepr              = substr(jsonencode(s.args), 0, 1024)
        kwargsrepr            = substr(jsonencode(s.kwargs), 0, 1024)
        origin                = "eventbridge-scheduler"
        ignore_result         = s.ignore_result
        replaced_task_nesting = 0
        stamped_headers       = null
        stamps                = {}
      }
      "properties" = {
        correlation_id = local.messages[key].task_id
        reply_to       = null
        delivery_mode  = 2
        delivery_info  = { exchange = "", routing_key = var.queue_name }
        priority       = 0
        body_encoding  = "base64"
        delivery_tag   = uuidv5("url", "${var.name}/${key}/delivery")
      }
    }))
  }
}

# Runs that could not be delivered after the retries (the queue was unreachable, a permission is missing...)
resource "aws_sqs_queue" "dlq" {
  name                      = "${var.name}-schedules-dlq"
  message_retention_seconds = var.dlq_retention_seconds
  sqs_managed_sse_enabled   = true
  tags                      = var.tags
}

resource "aws_scheduler_schedule_group" "this" {
  name = var.name
  tags = var.tags
}

data "aws_iam_policy_document" "trust" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }

    # confused deputy: only schedules of this account
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

data "aws_iam_policy_document" "send" {
  statement {
    sid       = "SendTasks"
    actions   = ["sqs:SendMessage"]
    resources = [var.queue_arn, aws_sqs_queue.dlq.arn]
  }
}

resource "aws_iam_role" "scheduler" {
  name               = "${var.name}-scheduler"
  assume_role_policy = data.aws_iam_policy_document.trust.json
  tags               = var.tags
}

resource "aws_iam_role_policy" "scheduler" {
  name   = "send-tasks"
  role   = aws_iam_role.scheduler.id
  policy = data.aws_iam_policy_document.send.json
}

resource "aws_scheduler_schedule" "this" {
  for_each = var.schedules

  name        = each.key
  group_name  = aws_scheduler_schedule_group.this.name
  description = each.value.description != "" ? each.value.description : "Celery task ${each.value.task}"
  state       = each.value.enabled ? "ENABLED" : "DISABLED"

  schedule_expression          = each.value.expression
  schedule_expression_timezone = each.value.timezone

  flexible_time_window {
    mode                      = each.value.flexible_minutes > 0 ? "FLEXIBLE" : "OFF"
    maximum_window_in_minutes = each.value.flexible_minutes > 0 ? each.value.flexible_minutes : null
  }

  target {
    arn      = var.queue_arn
    role_arn = aws_iam_role.scheduler.arn
    input    = local.bodies[each.key]

    retry_policy {
      maximum_retry_attempts       = each.value.retry_attempts
      maximum_event_age_in_seconds = each.value.max_age_seconds
    }

    dead_letter_config {
      arn = aws_sqs_queue.dlq.arn
    }
  }

  depends_on = [aws_iam_role_policy.scheduler]
}
