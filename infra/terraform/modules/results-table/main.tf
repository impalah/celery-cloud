# The Celery result backend. The layout is fixed by Celery's DynamoDB backend: ONE string hash
# key called `id` and no sort key. TTL is enabled on the attribute `ttl`, which the runner writes
# (RESULT_TTL_SECONDS): without it results would be kept forever.

resource "aws_dynamodb_table" "this" {
  name         = var.name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "id"

  attribute {
    name = "id"
    type = "S"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = var.point_in_time_recovery
  }

  server_side_encryption {
    enabled = true
  }

  deletion_protection_enabled = var.deletion_protection

  tags = var.tags
}
