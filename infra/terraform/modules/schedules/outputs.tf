output "group_name" {
  description = "Schedule group (aws scheduler list-schedules --group-name <this>)"
  value       = aws_scheduler_schedule_group.this.name
}

output "role_arn" {
  value = aws_iam_role.scheduler.arn
}

output "dlq_url" {
  description = "Runs that could not be delivered to the queue"
  value       = aws_sqs_queue.dlq.url
}

output "schedule_arns" {
  value = { for k, s in aws_scheduler_schedule.this : k => s.arn }
}

output "task_ids" {
  description = "The task id every run of each schedule carries"
  value       = { for k, m in local.messages : k => m.task_id }
}

output "messages" {
  description = "The SQS message body of each schedule (what Input holds)"
  value       = local.bodies
}
