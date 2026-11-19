# The repository of the runner image. Build and push the image after the first apply (README).

module "registry" {
  source = "../../modules/ecr-repository"

  name         = "${local.name}-runner"
  force_delete = var.ecr_force_delete
}
