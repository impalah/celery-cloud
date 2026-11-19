variable "name" {
  description = "Name of the queue; the dead-letter queue is called <name>-dlq"
  type        = string
}

variable "visibility_timeout_seconds" {
  description = "Time a received message is hidden. Must be at least the timeout of the function that reads the queue (AWS recommends six times)"
  type        = number
  default     = 1800

  validation {
    condition     = var.visibility_timeout_seconds >= 0 && var.visibility_timeout_seconds <= 43200
    error_message = "visibility_timeout_seconds must be between 0 and 43200 (12 hours)."
  }
}

variable "message_retention_seconds" {
  description = "How long an unprocessed message is kept (keep the result TTL of the runner longer than this)"
  type        = number
  default     = 345600
}

variable "max_receive_count" {
  description = "Receives before a message moves to the dead-letter queue"
  type        = number
  default     = 5
}

variable "dlq_retention_seconds" {
  description = "How long the dead-letter queue keeps a message (14 days, the maximum)"
  type        = number
  default     = 1209600
}

variable "tags" {
  description = "Extra tags"
  type        = map(string)
  default     = {}
}
