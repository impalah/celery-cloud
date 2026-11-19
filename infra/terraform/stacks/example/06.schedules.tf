# Periodic tasks (celery beat's job) with EventBridge Scheduler. Optional: with no entries in
# var.schedules nothing is created.

module "schedules" {
  count  = length(var.schedules) > 0 ? 1 : 0
  source = "../../modules/schedules"

  name       = local.name
  queue_arn  = module.queue.queue_arn
  queue_name = module.queue.queue_name
  schedules  = var.schedules
}
