import json
import os
from typing import Any

from dotenv import load_dotenv

# Load variables from dotenv file
load_dotenv()

_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off", ""}


class Settings:
    """Settings class, read once from environment variables."""

    def __init__(self) -> None:
        """Init configuration from environment variables"""

        self.CELERY_BACKEND_TABLE: str = self.get_env_variable(
            "CELERY_BACKEND_TABLE", "celery"
        )
        self.CELERY_BACKEND_REGION: str = self.get_env_variable(
            "CELERY_BACKEND_REGION", "eu-west-1"
        )

        self.LOG_LEVEL: str = self.get_env_variable("LOG_LEVEL", "INFO")
        self.LOG_FORMAT: str = self.get_env_variable(
            "LOG_FORMAT",
            (
                "<green>{time:YYYY-MM-DD HH:mm:ss}</green> "
                "| <level>{level: <8}</level> | trace_id={extra[trace_id]} "
                "| <cyan>{name}</cyan>:<cyan>{function}</cyan>:"
                "<cyan>{line}</cyan> - <level>{message}</level>"
            ),
        )

        self.LOG_ENQUEUE: bool = self.get_env_bool("LOG_ENQUEUE", False)
        # Dump local variables in tracebacks. It can leak task arguments to the
        # logs, so it is disabled by default.
        self.LOG_DIAGNOSE: bool = self.get_env_bool("LOG_DIAGNOSE", False)

        # Circuit breaker and retries config
        self.CB_FAIL_MAX: int = self.get_env_int("CB_FAIL_MAX", 5)
        self.CB_RESET_TIMEOUT: int = self.get_env_int("CB_RESET_TIMEOUT", 60)
        self.MAX_ATTEMPTS: int = self.get_env_int("MAX_ATTEMPTS", 5)

        # Seconds a stored result is kept. It is written as the `ttl` attribute
        # (epoch seconds, the field Celery's DynamoDB backend uses); DynamoDB
        # only deletes expired items if TTL is enabled on that attribute in the
        # table, so the value is inert until then. 0 disables the attribute.
        self.RESULT_TTL_SECONDS: int = self.get_env_int("RESULT_TTL_SECONDS", 86400)
        if self.RESULT_TTL_SECONDS < 0:
            raise ValueError(
                "Environment variable 'RESULT_TTL_SECONDS' must be 0 (no expiry) "
                f"or a positive number of seconds, got {self.RESULT_TTL_SECONDS}"
            )

        # Seconds to wait for a remote lambda to answer. Below the 900 s maximum of the
        # runner itself, so a slow remote function is recorded as FAILURE instead of
        # the whole invocation being killed
        self.LAMBDA_INVOKE_TIMEOUT: int = self.get_env_int(
            "LAMBDA_INVOKE_TIMEOUT", 840
        )

        # Seconds kept free before the Lambda timeout: a task is stopped (and its
        # FAILURE stored) this long before AWS would kill the function, and records
        # of a batch that would start with less time left are returned to SQS.
        self.TIMEOUT_MARGIN_SECONDS: int = self.get_env_int(
            "TIMEOUT_MARGIN_SECONDS", 10
        )
        if self.TIMEOUT_MARGIN_SECONDS < 0:
            raise ValueError(
                "Environment variable 'TIMEOUT_MARGIN_SECONDS' must be >= 0, "
                f"got {self.TIMEOUT_MARGIN_SECONDS}"
            )

        # Store name, args, kwargs, worker, retries and queue in the result (what
        # Celery's `result_extended` setting reads). Opt-in: args may be sensitive.
        self.RESULT_EXTENDED: bool = self.get_env_bool("RESULT_EXTENDED", False)

        # How results are written (Celery's ``result_serializer``: the client must use
        # the same). json, msgpack or yaml; the last two need the matching extra.
        self.RESULT_SERIALIZER: str = self.get_env_variable(
            "RESULT_SERIALIZER", "json"
        ).lower()
        if self.RESULT_SERIALIZER not in ("json", "msgpack", "yaml"):
            raise ValueError(
                "Environment variable 'RESULT_SERIALIZER' must be json, msgpack or "
                f"yaml, got {self.RESULT_SERIALIZER!r}"
            )

        # Records of a batch processed at the same time (threads). 1 = one after the
        # other. Above 1 the time limits cannot interrupt a task (signals only work
        # in the main thread); only the check before starting each record applies.
        self.BATCH_CONCURRENCY: int = self.get_env_int("BATCH_CONCURRENCY", 1)
        if self.BATCH_CONCURRENCY < 1:
            raise ValueError(
                "Environment variable 'BATCH_CONCURRENCY' must be >= 1, "
                f"got {self.BATCH_CONCURRENCY}"
            )

        # Modules imported once when the function starts (to register signals)
        self.INIT_MODULES: list[str] = [
            name.strip()
            for name in self.get_env_variable("INIT_MODULES", "").split(",")
            if name.strip()
        ]

        # CloudWatch metrics (Embedded Metric Format) written to the log
        self.METRICS_ENABLED: bool = self.get_env_bool("METRICS_ENABLED", False)
        self.METRICS_NAMESPACE: str = self.get_env_variable(
            "METRICS_NAMESPACE", "CeleryCloud"
        )

        # Debug server. The host is loopback by default: the debugger gives
        # remote code execution to anyone who can reach the port.
        self.SERVER_DEBUG_PORT: int = self.get_env_int("SERVER_DEBUG_PORT", 5890)
        self.DEBUG_HOST: str = self.get_env_variable("DEBUG_HOST", "127.0.0.1")
        self.DEBUG_MODE: bool = self.get_env_bool("DEBUG_MODE", False)

        self.TASKS: dict[str, str] = self._parse_tasks(
            self.get_env_variable("TASKS", "{}")
        )

    @staticmethod
    def get_env_variable(var_name: str, default: Any = None) -> Any:
        """Get environment variable or default value

        Args:
            var_name (str): Name of the environment variable.
            default (Any, optional): Value used when it is not defined.

        Raises:
            OSError: If the variable is not defined and has no default.

        Returns:
            Any: The raw value (a ``str`` when it comes from the environment).
        """

        value: Any = os.getenv(var_name, default)
        if value is None:
            raise OSError(
                f"Environment variable '{var_name}' "
                f"is not defined and does not have default value."
            )
        return value

    @classmethod
    def get_env_int(cls, var_name: str, default: int) -> int:
        """Get an environment variable as ``int``.

        Raises:
            ValueError: If the value is not an integer.
        """
        raw = cls.get_env_variable(var_name, default)
        try:
            return int(raw)
        except (TypeError, ValueError) as e:
            raise ValueError(
                f"Environment variable '{var_name}' must be an integer, got {raw!r}"
            ) from e

    @classmethod
    def get_env_bool(cls, var_name: str, default: bool) -> bool:
        """Get an environment variable as ``bool``.

        Accepts 1/true/yes/on and 0/false/no/off (case insensitive).

        Raises:
            ValueError: If the value is not a recognised boolean.
        """
        raw = cls.get_env_variable(var_name, default)
        if isinstance(raw, bool):
            return raw
        value = str(raw).strip().lower()
        if value in _TRUE_VALUES:
            return True
        if value in _FALSE_VALUES:
            return False
        raise ValueError(
            f"Environment variable '{var_name}' must be a boolean "
            f"(true/false), got {raw!r}"
        )

    @staticmethod
    def _parse_tasks(raw: str) -> dict[str, str]:
        """Parse and validate the TASKS JSON dictionary.

        Raises:
            ValueError: If it is not a JSON object of ``name -> scheme://...``.
        """
        try:
            tasks = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"Environment variable 'TASKS' is not valid JSON: {e}"
            ) from e

        if not isinstance(tasks, dict):
            raise ValueError("Environment variable 'TASKS' must be a JSON object")

        for name, url in tasks.items():
            if not isinstance(url, str) or "://" not in url:
                raise ValueError(
                    f"Task '{name}' in 'TASKS' must map to a 'scheme://...' url, "
                    f"got {url!r}"
                )
        return tasks


settings = Settings()
