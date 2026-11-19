# Plan-level tests with a mocked AWS provider: no credentials, nothing is created.
# Run with `terraform test` (check.sh does).

mock_provider "aws" {
  mock_resource "aws_sqs_queue" {
    defaults = {
      arn = "arn:aws:sqs:eu-central-1:123456789012:mock-queue"
      url = "https://sqs.eu-central-1.amazonaws.com/123456789012/mock-queue"
    }
  }

  mock_resource "aws_dynamodb_table" {
    defaults = {
      arn = "arn:aws:dynamodb:eu-central-1:123456789012:table/mock-table"
    }
  }

  mock_resource "aws_ecr_repository" {
    defaults = {
      repository_url = "123456789012.dkr.ecr.eu-central-1.amazonaws.com/mock"
    }
  }

  mock_resource "aws_iam_role" {
    defaults = {
      arn = "arn:aws:iam::123456789012:role/mock"
    }
  }

  mock_resource "aws_lambda_function" {
    defaults = {
      arn = "arn:aws:lambda:eu-central-1:123456789012:function:mock"
    }
  }

  mock_resource "aws_cloudwatch_log_group" {
    defaults = {
      arn = "arn:aws:logs:eu-central-1:123456789012:log-group:/aws/lambda/mock"
    }
  }

  mock_data "aws_iam_policy_document" {
    defaults = {
      json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}"
    }
  }
}

variables {
  aws_account_id = "123456789012"
  owner          = "tests"
}

run "first_apply_has_no_function_yet" {
  command = plan

  assert {
    condition     = length(module.runner) == 0
    error_message = "The function must not exist until an image tag is set."
  }

  assert {
    condition     = output.runner_function == null
    error_message = "runner_function must be null without an image."
  }
}

run "the_queue_waits_six_function_timeouts" {
  command = plan

  variables {
    runner_timeout = 120
  }

  assert {
    condition     = output.queue_visibility_timeout_seconds == 720
    error_message = "The visibility timeout must be six times the function timeout."
  }

  assert {
    condition     = module.queue.queue_name == "celery-cloud-example-queue"
    error_message = "The queue name must be <project>-<environment>-queue."
  }
}

run "with_an_image_the_function_is_created" {
  command = plan

  variables {
    runner_image_tag = "7"
    tasks            = { "calculator.add" = "task://calculator/add" }
  }

  assert {
    condition     = length(module.runner) == 1
    error_message = "The function must exist once an image tag is set."
  }

  assert {
    condition     = module.runner[0].function_name == "celery-cloud-example-runner"
    error_message = "Unexpected function name."
  }
}

run "the_timeout_cannot_exceed_what_lambda_allows" {
  command = plan

  variables {
    runner_timeout = 901
  }

  expect_failures = [var.runner_timeout]
}

run "an_unknown_architecture_is_rejected" {
  command = plan

  variables {
    runner_architecture = "mips"
  }

  expect_failures = [var.runner_architecture]
}

run "the_longest_function_timeout_gives_5400_seconds" {
  command = plan

  variables {
    runner_timeout = 900
  }

  assert {
    condition     = output.queue_visibility_timeout_seconds == 5400
    error_message = "900 s x 6 = 5400 s, well below the 12 hour limit."
  }
}

run "without_schedules_there_is_no_scheduler" {
  command = plan

  assert {
    condition     = length(module.schedules) == 0 && output.schedule_group == null
    error_message = "No scheduler resources without schedules."
  }
}

run "a_schedule_sends_a_celery_message_to_the_queue" {
  command = plan

  variables {
    schedules = {
      nightly = {
        task       = "calculator.add"
        expression = "cron(0 3 * * ? *)"
        args       = [1, 2]
        timezone   = "Europe/Madrid"
      }
    }
  }

  assert {
    condition     = length(module.schedules) == 1
    error_message = "A schedule must create the scheduler module."
  }

  assert {
    condition     = jsondecode(base64decode(module.schedules[0].messages["nightly"])).headers.task == "calculator.add"
    error_message = "The message must carry the task name."
  }

  assert {
    condition     = jsondecode(base64decode(jsondecode(base64decode(module.schedules[0].messages["nightly"])).body))[0] == [1, 2]
    error_message = "The message body must carry the arguments."
  }

  assert {
    condition     = jsondecode(base64decode(module.schedules[0].messages["nightly"])).properties.delivery_info.routing_key == "celery-cloud-example-queue"
    error_message = "The routing key must be the queue name."
  }
}

run "a_schedule_must_use_the_eventbridge_syntax" {
  command = plan

  variables {
    schedules = {
      bad = {
        task       = "calculator.add"
        expression = "0 3 * * *"
      }
    }
  }

  expect_failures = [var.schedules]
}
