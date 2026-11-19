locals {
  # Every resource name starts with the project and the environment; the provider adds the tags
  name = "${var.project}-${var.environment}"

  # The function is created only when there is an image to run (see variable runner_image_tag)
  deploy_runner = var.runner_image_tag != ""

  # AWS recommends a visibility timeout of six times the function timeout (12 hours at most)
  visibility_timeout = min(var.runner_timeout * 6, 43200)
}
