# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

`celery-cloud` is a "Celery serverless" runner: an AWS Lambda handler that receives SQS messages written by a regular Celery client (SQS broker), decodes the Celery task, executes it (locally or by invoking another Lambda), and stores status/result in a DynamoDB backend that the Celery client can read. Python >=3.12, managed with `uv`, built with hatchling. Source in `src/celery_cloud/`.

## Commands

Use the `makefile` (all via `uv run`):

- `make venv` — recreate `.venv` and `uv sync`
- `make lint` / `make format` / `make type-check` (mypy strict) / `make security-check` (bandit) / `make check` (all four; note `format` rewrites files)
- `make test` — full pytest run with coverage (`--maxfail=1`, `--doctest-modules`, writes junit/coverage files)
- Single test: `uv run pytest tests/test_call_task.py::test_name -v`
- `make bump-version PART=patch|minor|major` — explicit version bump (`uv version --bump`, updates pyproject.toml **and** uv.lock). `build`/`release`/`docker-build` do not bump; the release workflow does not bump either (versions are evolved manually and committed). Docker build/push needs AWS credentials (profile `pak`).

Local debugging: `src/celery_cloud/debug_server.py` is a FastAPI app exposing `POST /lambda` that feeds an event dict to `lambda_handler`; with `DEBUG_MODE=true` it waits for a debugpy client on `SERVER_DEBUG_PORT` (5890). Run e.g. `uv run uvicorn celery_cloud.debug_server:app`.

## Architecture

Request flow (`runners/aws_lambda.py::lambda_handler`): every SQS record is processed independently by `_process_record` (never raises; records can run in threads with `BATCH_CONCURRENCY`). It wraps `_process_record_inner`, which does:
1. `SQSEvent.from_lambda` parses the event; `SQSMessage.from_record` decodes the Celery envelope and `get_task()` builds the `Task` (headers + `embed`: callbacks, errbacks, chain, chord). **Args/kwargs come from the message body** (`[args, kwargs, embed]`), never from the truncated `argsrepr`. `serialization.py` handles json/msgpack/yaml and gzip(=kombu zlib)/bz2/lzma; pickle is refused on purpose.
2. **eta**: a future `eta` is held by `messaging.delay_message` (the same message back to the queue with `DelaySeconds` ≤ 900, rounded up); nothing is registered.
3. `TaskModel` (PynamoDB, `models/task_model.py`) registers the task with a **conditional write** (`DuplicateTaskException` ⇒ duplicate; `RevokedTaskException` ⇒ revoked by the client; a message whose `retries` is higher than the item's extra `attempt` attribute is a retry and takes the task over). `ignore_result` tasks write nothing; tasks past `expires` are stored `REVOKED`; every write sets `ttl`; a result over `MAX_RESULT_BYTES` raises `ResultTooLargeException` ⇒ `FAILURE`. Celery meta is stored as raw bytes in `RESULT_SERIALIZER` (json default): `STARTED`, then `SUCCESS`/`FAILURE`/`RETRY`/custom. The hash key is intentionally `str(b"celery-task-meta-<id>")`.
4. `call_task` resolves `task.task` in `settings.TASKS` (allowlist) or the built-ins `celery.map`/`celery.starmap` (`runners/builtin_tasks.py`), applies the time limits (`deadline.py`: message limits win over `@task` ones, plus the Lambda deadline minus `TIMEOUT_MARGIN_SECONDS`, via `SIGALRM`, main thread only) and hands the route to `TaskExecutor` (Strategy pattern, `runners/task_execution_strategy.py`):
   - `lambda://<function-arn>` → `LambdaTaskExecutionStrategy` (per-ARN `pybreaker`, `tenacity` only for `LambdaInvocationError`, a `LambdaFunctionError` is neither retried nor counted).
   - `task://<module>/<function>` → `LocalTaskExecutionStrategy`: plain functions get `function(args, kwargs)`; functions decorated with `celery_cloud.task` (`tasks.py`) get natural arguments and, with `bind=True`, a `TaskContext` (`retry`, `update_state`, `is_revoked`, `request`). The runner publishes a `Runtime` through a context variable (`runtime.py`) while the task runs.
5. Outcome: `Retry` ⇒ the message is re-sent with `retries+1`/`eta` and state `RETRY`; `Ignore` ⇒ state untouched; `Reject(requeue)` ⇒ item deleted + `batchItemFailures`, else `REJECTED`; success/failure ⇒ stored, then `runners/canvas.py` sends callbacks/chain steps and does the chord accounting (`models/canvas_model.py`: Celery's `celery-taskset-meta-*` and `chord-unlock-*` items). Dispatch problems are logged, never fail the task. **Failures report the original exception** (`_failure_payload` unwraps `TaskExecutionException.__cause__`). `signals.py` (`task_prerun`...), `metrics.py` (EMF) and `INIT_MODULES` hook around it.
6. Response: a serialized `LambdaResponse` (processed/failed/skipped/delayed). Only backend failures, `Reject(requeue=True)` and records that cannot start in time are returned in `batchItemFailures` (needs `ReportBatchItemFailures`).

`client.py` is the only module meant for client applications (`install(app)` makes `result.revoke()` work through the backend); it must not import the runner settings (a test checks it). `messaging.py` builds/sends Celery protocol-2 messages (validated against real Celery 5.7 messages).

To add a new scheme, subclass `TaskExecutionStrategy` and register it in `TaskExecutor.strategies`.

Configuration is entirely environment variables (or `.env` via python-dotenv), read once in `settings.py` into a singleton `settings`. Use `get_env_int`/`get_env_bool` for new settings: raw `os.getenv` values are always `str` (a `"false"` string is truthy). `TASKS` is a JSON dict mapping Celery task name → route URL (see `.env.template`). Logging uses loguru with a per-invocation KSUID `trace_id` held in a context var (`logging.py`).

Errors are custom exceptions in `exceptions/` (all derive from `runner_base_exception`); `lambda_handler` converts them into a `LambdaResponse` (status `completed`/`error`) rather than raising.

The `Dockerfile` builds an AWS Lambda image (handler `celery_cloud.runners.aws_lambda.lambda_handler`) that only supports remote (`lambda://`) tasks unless extended with local code. Releases are driven by `.github/workflows/release.yml`; GitHub Actions are pinned by commit SHA and kept current by Dependabot (`.github/dependabot.yml`).

## Notes

- Tests live in `tests/` (pytest). `documentation/evidence/e2e/` has end-to-end checks with a REAL Celery client against moto (phase1/phase23/phase4_map/phase5 scripts, `runner_loop.py` emulates the event source mapping): run them when touching the message protocol, they found bugs the unit tests could not (kombu's "gzip" is zlib). Unit tests mock boto3; `tests/integration/` runs the handler against a simulated DynamoDB (`moto`, fake credentials, no real AWS). Add backend behaviour tests there, mocks hid a real bug before. `tests/sqs_helpers.py::build_sqs_record` (fixtures in `tests/conftest.py`) builds realistic SQS/Celery events: prefer it over hand-made mocks of the message classes. Lambda strategy tests patch `tenacity.nap.time.sleep` to avoid real waits.
- Quality gate (also run in CI): `uv run ruff check src`, `uv run mypy src`, `uv run bandit -r src`, `uv run pytest`; all must stay at 0 issues.
- Mutation testing is manual and not part of CI: `make mutation` / `make mutation-report` (mutmut, config in `[tool.mutmut]`). Last run (16 modules, 3021 mutants): 92.5 % killed; the 226 survivors are log/error-text or equivalent mutants (see `documentation/04-mutation-testing.md`). Assert exact `message`/`detail` of exceptions in new tests: they are returned to clients.
- Sphinx documentation: sources in `pages_source/` (the code of its examples is in `pages_source/examples/`, and the server ones are tested by `tests/integration/test_docs_examples.py`), generated HTML in `docs/` (GitHub Pages; committed by `.github/workflows/docs.yml`, never edit it by hand). `make docs` builds with `-W` (warnings are errors), `make docs-serve` serves it. Docstrings are Google style (napoleon); add new modules to `pages_source/api/`.
- Terraform for the basic infrastructure (queue + DLQ, result table, ECR, runner Lambda, client policy) is in `infra/terraform/` (modules + `stacks/example`, mocked-provider tests in `example.tftest.hcl`); `make infra-check` validates it without credentials. It was applied once on a real account (2026-11-19, environment `test`, local state in `stacks/example/terraform.tfstate`, git-ignored); read the plan before applying anyway.
- **Pending work is listed in `documentation/08-pendientes.md`** (nothing is committed yet; real-AWS verification, release and Pages setup are still open).
- `documentation/` holds the quality audit (findings, remediation plan and log) and the script that reproduces the original bugs.
- Only SQS events are supported as event source. See README "Known limitations" (no beat, no rate_limit, no pickle).
- `README.md` documents the Celery client setup, the env vars table and the runner behaviour.
