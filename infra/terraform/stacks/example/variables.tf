variable "aws_account_id" {
  description = "The only AWS account this stack may touch (the provider refuses any other)"
  type        = string
}

variable "region" {
  description = "Region of everything: the queue, the table, the repository and the function must share it"
  type        = string
  default     = "eu-central-1"
}

variable "project" {
  description = "Project name: prefix of every resource and a tag"
  type        = string
  default     = "celery-cloud"
}

variable "environment" {
  description = "Environment name: part of every resource name and a tag"
  type        = string
  default     = "example"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,15}$", var.environment))
    error_message = "environment must be short lower-case letters, digits and dashes."
  }
}

variable "owner" {
  description = "Who owns these resources (tag)"
  type        = string
}

# --- the runner ---------------------------------------------------------------------------------

variable "runner_image_tag" {
  description = "Tag of the runner image in the repository. Empty on the first apply (the repository does not hold an image yet): the function is created once you push one and set the tag"
  type        = string
  default     = ""
}

variable "tasks" {
  description = "The TASKS setting: Celery task name => task://<module>/<function> or lambda://<function-arn>"
  type        = map(string)
  default     = {}
}

variable "remote_function_arns" {
  description = "Lambda functions that lambda:// tasks invoke"
  type        = list(string)
  default     = []
}

variable "runner_environment" {
  description = "Other settings of the runner (LOG_LEVEL, RESULT_TTL_SECONDS, BATCH_CONCURRENCY, METRICS_ENABLED...)"
  type        = map(string)
  default     = {}
}

variable "runner_timeout" {
  description = "Function timeout in seconds (at most 900: no task can run longer)"
  type        = number
  default     = 300

  validation {
    condition     = var.runner_timeout >= 1 && var.runner_timeout <= 900
    error_message = "runner_timeout must be between 1 and 900 seconds (the Lambda maximum)."
  }
}

variable "runner_memory_mb" {
  type    = number
  default = 512
}

variable "runner_architecture" {
  description = "x86_64 or arm64: the image must be built for it"
  type        = string
  default     = "x86_64"

  validation {
    condition     = contains(["x86_64", "arm64"], var.runner_architecture)
    error_message = "runner_architecture must be x86_64 or arm64."
  }
}

variable "runner_batch_size" {
  type    = number
  default = 10
}

variable "runner_max_concurrency" {
  description = "Most invocations at once (2 to 1000); null = no limit. Useful to cap the cost of a test"
  type        = number
  default     = null
}

variable "log_retention_days" {
  type    = number
  default = 30
}

# --- the queue and the table ----------------------------------------------------------------------

variable "queue_message_retention_seconds" {
  description = "How long an unprocessed message lives (keep RESULT_TTL_SECONDS of the runner longer than this)"
  type        = number
  default     = 345600
}

variable "queue_max_receive_count" {
  description = "Receives before a message goes to the dead-letter queue"
  type        = number
  default     = 5
}

variable "table_deletion_protection" {
  type    = bool
  default = false
}

variable "ecr_force_delete" {
  description = "Let `terraform destroy` delete the repository even if it holds images (handy for a test environment)"
  type        = bool
  default     = true
}

# --- the client -------------------------------------------------------------------------------------

variable "create_client_user" {
  description = "Create an IAM user with the client policy. No access key is created (it would live in the state): make one yourself, or attach the policy to the role of your application"
  type        = bool
  default     = false
}

# --- periodic tasks ---------------------------------------------------------------------------------

variable "schedules" {
  description = "Periodic tasks (EventBridge Scheduler), by name: task, expression (cron(...)/rate(...)), args, kwargs, timezone, enabled... See modules/schedules. Empty = no scheduler resources"
  type = map(object({
    task             = string
    expression       = string
    args             = optional(list(any), [])
    kwargs           = optional(map(any), {})
    timezone         = optional(string, "UTC")
    enabled          = optional(bool, true)
    ignore_result    = optional(bool, true)
    time_limit       = optional(number)
    soft_time_limit  = optional(number)
    description      = optional(string, "")
    retry_attempts   = optional(number, 3)
    max_age_seconds  = optional(number, 3600)
    flexible_minutes = optional(number, 0)
  }))
  default = {}

  validation {
    condition     = alltrue([for s in values(var.schedules) : can(regex("^(cron|rate|at)\\(.+\\)$", s.expression))])
    error_message = "expression must be cron(...), rate(...) or at(...) (EventBridge syntax, not crontab)."
  }
}
