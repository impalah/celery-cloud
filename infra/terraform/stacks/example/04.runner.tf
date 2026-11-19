# The runner function and its event source mapping. Created once runner_image_tag is set, i.e.
# after the image has been pushed to the repository of 03.registry.tf.

module "runner" {
  source = "../../modules/lambda-runner"
  count  = local.deploy_runner ? 1 : 0

  name       = "${local.name}-runner"
  image_uri  = "${module.registry.repository_url}:${var.runner_image_tag}"
  queue_arn  = module.queue.queue_arn
  table_arn  = module.results.table_arn
  table_name = module.results.table_name
  region     = var.region

  tasks                 = var.tasks
  remote_function_arns  = var.remote_function_arns
  environment_variables = var.runner_environment

  timeout             = var.runner_timeout
  memory_size         = var.runner_memory_mb
  architecture        = var.runner_architecture
  batch_size          = var.runner_batch_size
  maximum_concurrency = var.runner_max_concurrency
  log_retention_days  = var.log_retention_days
}
