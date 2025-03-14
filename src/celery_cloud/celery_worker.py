import platform
from typing import List

from celery_cloud.core.settings import settings
from celery_cloud.task import app


"""

celery -A celery_cloud.celery_worker.app worker --loglevel=info --concurrency=2

For windows
celery -A celery_cloud.celery_worker.app worker --loglevel=info -P solo

"""


def start_worker():
    print("Starting celery worker")

    argv: List[str] = [
        "worker",
        f"--loglevel={settings.LOG_LEVEL.lower()}",
    ]

    if platform.system() == "Windows":
        argv.append("-P")
        argv.append("solo")
    else:
        argv.append(f"--concurrency={settings.CELERY_WORKERS}")

    app.worker_main(argv=argv)
