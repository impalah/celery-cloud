# uv is copied from its official image with a pinned version (no `curl | sh`)
FROM ghcr.io/astral-sh/uv:0.10.8 AS uv

FROM public.ecr.aws/lambda/python:3.12

COPY --from=uv /uv /usr/local/bin/uv

# Generate requirements.txt from the lock file (production dependencies only)
COPY pyproject.toml uv.lock README.md ${LAMBDA_TASK_ROOT}/
RUN uv export --no-emit-project --no-hashes --frozen --no-dev --no-editable \
        -o ${LAMBDA_TASK_ROOT}/requirements.txt && \
    pip install --no-cache-dir -r ${LAMBDA_TASK_ROOT}/requirements.txt && \
    rm -f /usr/local/bin/uv

# Copy function code
COPY src/. ${LAMBDA_TASK_ROOT}/

# Set the CMD to your handler (could also be done as a parameter override outside of the Dockerfile)
CMD [ "celery_cloud.runners.aws_lambda.lambda_handler" ]
