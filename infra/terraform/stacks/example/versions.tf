terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  # use_lockfile needs Terraform 1.10+ (S3 native locking, no DynamoDB table)
  required_version = ">= 1.10.0, < 2.0.0"

  # Remote state in a bucket you already own (see application.backend.conf.template)
  backend "s3" {
  }
}
