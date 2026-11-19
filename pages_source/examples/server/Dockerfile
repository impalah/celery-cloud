# The runner image already contains celery-cloud and the Lambda handler.
# Use a tag that exists in https://gallery.ecr.aws/e2b2x4l7/celery-cloud/lambda-runner
FROM public.ecr.aws/e2b2x4l7/celery-cloud/lambda-runner:<tag>

# Local tasks: copy them next to the handler so `task://calculator/add` can import them
COPY calculator.py reports.py ${LAMBDA_TASK_ROOT}/

# Extra dependencies of your tasks (reports.py uses pydantic, which the runner
# already ships, so nothing to install here)
# RUN pip install --no-cache-dir <package>
