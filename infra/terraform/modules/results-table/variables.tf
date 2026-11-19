variable "name" {
  description = "Name of the table (CELERY_BACKEND_TABLE and the table of the client's result_backend)"
  type        = string
}

variable "point_in_time_recovery" {
  description = "Continuous backups. Results are transient, so it is off by default"
  type        = bool
  default     = false
}

variable "deletion_protection" {
  description = "Refuse to delete the table"
  type        = bool
  default     = false
}

variable "tags" {
  description = "Extra tags"
  type        = map(string)
  default     = {}
}
