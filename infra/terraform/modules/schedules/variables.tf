variable "name" {
  description = "Prefix of the schedule group, the role and the dead-letter queue"
  type        = string
}

variable "queue_arn" {
  description = "ARN of the Celery queue the schedules send to"
  type        = string
}

variable "queue_name" {
  description = "Name of the queue: the routing key of the messages (task_default_queue of the client)"
  type        = string
}

variable "schedules" {
  description = <<-EOT
    The periodic tasks (what celery beat's beat_schedule holds), by name:
    - task: the Celery task name (as in the TASKS setting of the runner)
    - expression: cron(...) or rate(...) (EventBridge syntax, not crontab)
    - args, kwargs: the arguments of the task
    - timezone: IANA name; Celery beat uses UTC by default
    - enabled: false creates it paused
    - ignore_result: true (the default) writes nothing to the result table, so every run
      executes; a schedule sends the same task id every time and the runner de-duplicates
      by id, so false makes only the first run execute
    - time_limit, soft_time_limit: seconds
  EOT
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
    error_message = "expression must be cron(...), rate(...) or at(...) (EventBridge syntax)."
  }
}

variable "dlq_retention_seconds" {
  description = "How long a run that could not be delivered to the queue is kept"
  type        = number
  default     = 1209600
}

variable "tags" {
  type    = map(string)
  default = {}
}
