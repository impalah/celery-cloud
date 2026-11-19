provider "aws" {
  region = var.region

  # The provider refuses any other account: a wrong AWS_PROFILE cannot touch it
  allowed_account_ids = [var.aws_account_id]

  default_tags {
    tags = {
      project     = var.project
      environment = var.environment
      owner       = var.owner
      managed-by  = "terraform"
    }
  }
}
