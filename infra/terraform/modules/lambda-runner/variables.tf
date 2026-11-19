variable "name" {
  description = "Name of the function and prefix of its role and log group"
  type        = string
}

variable "image_uri" {
  description = "URI of the runner image (<repo>:<tag>) in an ECR repository of this account and Region"
  type        = string
}

variable "queue_arn" {
  description = "ARN of the SQS queue the function reads (and sends to: eta, retries, workflows)"
  type        = string
}

variable "table_arn" {
  description = "ARN of the DynamoDB result table"
  type        = string
}

variable "table_name" {
  description = "Name of the result table (CELERY_BACKEND_TABLE)"
  type        = string
}

variable "region" {
  description = "Region of the table (CELERY_BACKEND_REGION)"
  type        = string
}

variable "tasks" {
  description = "The TASKS setting: Celery task name => task://<module>/<function> or lambda://<function-arn>"
  type        = map(string)
  default     = {}
}

variable "remote_function_arns" {
  description = "ARNs of the Lambda functions that lambda:// tasks invoke (the role may invoke exactly these)"
  type        = list(string)
  default     = []
}

variable "environment_variables" {
  description = "Other settings of the runner (LOG_LEVEL, RESULT_TTL_SECONDS, BATCH_CONCURRENCY, ...)"
  type        = map(string)
  default     = {}
}

variable "timeout" {
  description = "Function timeout in seconds (at most 900: no task can run longer)"
  type        = number
  default     = 300

  validation {
    condition     = var.timeout >= 1 && var.timeout <= 900
    error_message = "timeout must be between 1 and 900 seconds (the Lambda maximum)."
  }
}

variable "memory_size" {
  description = "Memory in MB"
  type        = number
  default     = 512
}

variable "architecture" {
  description = "x86_64 or arm64; the image must be built for it"
  type        = string
  default     = "x86_64"

  validation {
    condition     = contains(["x86_64", "arm64"], var.architecture)
    error_message = "architecture must be x86_64 or arm64."
  }
}

variable "batch_size" {
  description = "Messages per invocation"
  type        = number
  default     = 10
}

variable "maximum_concurrency" {
  description = "Most invocations running at once for this queue (2 to 1000); null = no limit"
  type        = number
  default     = null
}

variable "log_retention_days" {
  description = "Retention of the CloudWatch log group"
  type        = number
  default     = 30
}

variable "tags" {
  description = "Extra tags"
  type        = map(string)
  default     = {}
}
