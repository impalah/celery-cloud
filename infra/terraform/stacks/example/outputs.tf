output "queue_url" {
  description = "CELERY_QUEUE_URL of the client"
  value       = module.queue.queue_url
}

output "queue_visibility_timeout_seconds" {
  description = "Six times the function timeout, so a message is not redelivered while it is being processed"
  value       = local.visibility_timeout
}

output "queue_name" {
  description = "task_default_queue of the client"
  value       = module.queue.queue_name
}

output "dlq_url" {
  description = "Dead-letter queue: read it when messages do not get through"
  value       = module.queue.dlq_url
}

output "results_table" {
  description = "The table of the client's result_backend: dynamodb://@<region>/<table>"
  value       = module.results.table_name
}

output "result_backend" {
  description = "The result_backend of the Celery client"
  value       = "dynamodb://@${var.region}/${module.results.table_name}"
}

output "repository_url" {
  description = "Where to push the runner image"
  value       = module.registry.repository_url
}

output "runner_function" {
  description = "Name of the runner function (null until runner_image_tag is set)"
  value       = local.deploy_runner ? module.runner[0].function_name : null
}

output "runner_log_group" {
  description = "aws logs tail <this> --follow"
  value       = local.deploy_runner ? module.runner[0].log_group_name : null
}

output "client_policy_arn" {
  description = "Attach it to the identity of the application that uses the Celery client"
  value       = aws_iam_policy.client.arn
}

output "client_user" {
  description = "The IAM user for trying things out (null unless create_client_user)"
  value       = var.create_client_user ? aws_iam_user.client[0].name : null
}

output "schedule_group" {
  description = "EventBridge Scheduler group of the periodic tasks (null without schedules)"
  value       = length(module.schedules) > 0 ? module.schedules[0].group_name : null
}

output "schedules_dlq_url" {
  description = "Scheduled runs that could not be delivered to the queue (null without schedules)"
  value       = length(module.schedules) > 0 ? module.schedules[0].dlq_url : null
}
