# The Celery broker: the queue the client sends to and the runner reads, with its dead-letter queue.

module "queue" {
  source = "../../modules/sqs-queue"

  name                       = "${local.name}-queue"
  visibility_timeout_seconds = local.visibility_timeout
  message_retention_seconds  = var.queue_message_retention_seconds
  max_receive_count          = var.queue_max_receive_count
}
