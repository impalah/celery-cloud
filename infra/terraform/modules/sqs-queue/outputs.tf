output "queue_name" {
  description = "Name of the queue (task_default_queue of the Celery client)"
  value       = aws_sqs_queue.this.name
}

output "queue_url" {
  description = "URL of the queue (the client needs it in predefined_queues)"
  value       = aws_sqs_queue.this.url
}

output "queue_arn" {
  value = aws_sqs_queue.this.arn
}

output "dlq_arn" {
  value = aws_sqs_queue.dlq.arn
}

output "dlq_url" {
  value = aws_sqs_queue.dlq.url
}
