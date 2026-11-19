# The Celery result backend (hash key `id`, TTL on `ttl`).

module "results" {
  source = "../../modules/results-table"

  name                = "${local.name}-results"
  deletion_protection = var.table_deletion_protection
}
