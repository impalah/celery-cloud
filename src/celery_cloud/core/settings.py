import os
from typing import Any
from dotenv import load_dotenv

# Load variables from dotenv file
load_dotenv()


class Settings:
    """Settings class
    """

    def __init__(self):
        """Init configuration forn environmnent variables
        """

        self.CELERY_BROKER_URL: str = self.get_env_variable('CELERY_BROKER_URL', 'sqs://@')
        self.CELERY_BACKEND_URL: str = self.get_env_variable('CELERY_BACKEND_URL', 'dynamodb://@/?read=5&write=5')
        self.CELERY_TASK_DEFAULT_QUEUE: str = self.get_env_variable('CELERY_TASK_DEFAULT_QUEUE', 'celery-test-queue')
        self.CELERY_BROKER_SQS_QUEUE_URL: str = self.get_env_variable('CELERY_BROKER_SQS_QUEUE_URL', None)
        self.CELERY_BROKER_SQS_REGION: str = self.get_env_variable('CELERY_BROKER_SQS_REGION', None)
        self.LOG_LEVEL: str = self.get_env_variable('LOG_LEVEL', 'INFO')
        self.LOG_FORMAT: str = self.get_env_variable(
            "LOG_FORMAT",
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | trace_id={extra[trace_id]} | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",)


        self.CELERY_WORKERS: int = self.get_env_variable('CELERY_WORKERS', 2)


    @staticmethod
    def get_env_variable(var_name: str, default: Any=None)->Any:
        """Get environment variable or default value

        Args:
            var_name (str): _description_
            default (str, optional): _description_. Defaults to None.

        Raises:
            EnvironmentError: _description_

        Returns:
            str: _description_
        """

        value: Any = os.getenv(var_name, default)
        if value is None:
            raise EnvironmentError(f"Environment variable '{var_name}' is not defined and does not have default value.")
        return value


settings = Settings()


