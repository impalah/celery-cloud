# What the Celery client (your application) needs: send tasks, read results and, if it uses
# celery_cloud.client.install(app), revoke them. Attach this policy to the identity of the
# application; with create_client_user it also creates a user for trying things out.

data "aws_iam_policy_document" "client" {
  statement {
    sid       = "SendTasks"
    actions   = ["sqs:SendMessage"]
    resources = [module.queue.queue_arn]
  }

  statement {
    sid = "ReadResults"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:DescribeTable",
      # only for celery_cloud.client.install(app) (revoke)
      "dynamodb:PutItem",
      "dynamodb:UpdateItem",
    ]
    resources = [module.results.table_arn]
  }
}

resource "aws_iam_policy" "client" {
  name        = "${local.name}-client"
  description = "Send tasks to the ${local.name} queue and read their results"
  policy      = data.aws_iam_policy_document.client.json
}

resource "aws_iam_user" "client" {
  count = var.create_client_user ? 1 : 0
  name  = "${local.name}-client"
}

resource "aws_iam_user_policy_attachment" "client" {
  count      = var.create_client_user ? 1 : 0
  user       = aws_iam_user.client[0].name
  policy_arn = aws_iam_policy.client.arn
}
