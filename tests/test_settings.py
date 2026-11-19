import pytest

from celery_cloud.settings import Settings


def make(monkeypatch, **env):
    for key in (
        "CB_FAIL_MAX", "MAX_ATTEMPTS", "DEBUG_MODE", "LOG_ENQUEUE", "LOG_DIAGNOSE",
        "TASKS", "SERVER_DEBUG_PORT", "DEBUG_HOST", "LAMBDA_INVOKE_TIMEOUT",
    ):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return Settings()


def test_defaults_are_safe(monkeypatch):
    s = make(monkeypatch)
    assert s.DEBUG_MODE is False
    assert s.DEBUG_HOST == "127.0.0.1"
    assert s.LOG_DIAGNOSE is False
    assert s.TASKS == {}
    assert s.CB_FAIL_MAX == 5


def test_numbers_from_environment_are_ints(monkeypatch):
    """Regression: they were str and broke pybreaker/tenacity."""
    s = make(monkeypatch, CB_FAIL_MAX="3", MAX_ATTEMPTS="4", SERVER_DEBUG_PORT="6000")
    assert (s.CB_FAIL_MAX, s.MAX_ATTEMPTS, s.SERVER_DEBUG_PORT) == (3, 4, 6000)
    assert all(isinstance(v, int) for v in (s.CB_FAIL_MAX, s.MAX_ATTEMPTS))


@pytest.mark.parametrize("value,expected", [
    ("true", True), ("TRUE", True), ("1", True), ("yes", True), ("on", True),
    ("false", False), ("False", False), ("0", False), ("no", False), ("", False),
])
def test_booleans(monkeypatch, value, expected):
    """Regression: DEBUG_MODE="false" was truthy and enabled debugpy."""
    assert make(monkeypatch, DEBUG_MODE=value).DEBUG_MODE is expected


def test_invalid_boolean_is_rejected(monkeypatch):
    with pytest.raises(ValueError, match="DEBUG_MODE"):
        make(monkeypatch, DEBUG_MODE="maybe")


def test_invalid_integer_is_rejected(monkeypatch):
    with pytest.raises(ValueError, match="CB_FAIL_MAX"):
        make(monkeypatch, CB_FAIL_MAX="five")


def test_tasks_are_parsed(monkeypatch):
    s = make(monkeypatch, TASKS='{"a.b": "task://m/f", "c": "lambda://arn:x"}')
    assert s.TASKS == {"a.b": "task://m/f", "c": "lambda://arn:x"}


@pytest.mark.parametrize("raw", ["{not json", "[]", '{"a": 1}', '{"a": "no-scheme"}'])
def test_invalid_tasks_fail_with_clear_error(monkeypatch, raw):
    with pytest.raises(ValueError, match="TASKS"):
        make(monkeypatch, TASKS=raw)


def test_get_env_variable_requires_value():
    with pytest.raises(OSError):
        Settings.get_env_variable("SURELY_NOT_DEFINED_VAR_123")


# ---- exact defaults and environment variable names -------------------------

ALL_VARS = (
    "CELERY_BACKEND_TABLE", "CELERY_BACKEND_REGION", "LOG_LEVEL", "LOG_FORMAT",
    "LOG_ENQUEUE", "LOG_DIAGNOSE", "CB_FAIL_MAX", "CB_RESET_TIMEOUT",
    "MAX_ATTEMPTS", "LAMBDA_INVOKE_TIMEOUT", "SERVER_DEBUG_PORT", "DEBUG_HOST",
    "DEBUG_MODE", "TASKS", "RESULT_TTL_SECONDS", "TIMEOUT_MARGIN_SECONDS",
    "RESULT_EXTENDED", "RESULT_SERIALIZER", "BATCH_CONCURRENCY", "INIT_MODULES",
    "METRICS_ENABLED", "METRICS_NAMESPACE",
)

DEFAULT_LOG_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> "
    "| <level>{level: <8}</level> | trace_id={extra[trace_id]} "
    "| <cyan>{name}</cyan>:<cyan>{function}</cyan>:"
    "<cyan>{line}</cyan> - <level>{message}</level>"
)

DEFAULTS = {
    "CELERY_BACKEND_TABLE": "celery",
    "CELERY_BACKEND_REGION": "eu-west-1",
    "LOG_LEVEL": "INFO",
    "LOG_FORMAT": DEFAULT_LOG_FORMAT,
    "LOG_ENQUEUE": False,
    "LOG_DIAGNOSE": False,
    "CB_FAIL_MAX": 5,
    "CB_RESET_TIMEOUT": 60,
    "MAX_ATTEMPTS": 5,
    "LAMBDA_INVOKE_TIMEOUT": 840,
    "RESULT_TTL_SECONDS": 86400,
    "TIMEOUT_MARGIN_SECONDS": 10,
    "RESULT_EXTENDED": False,
    "RESULT_SERIALIZER": "json",
    "BATCH_CONCURRENCY": 1,
    "INIT_MODULES": [],
    "METRICS_ENABLED": False,
    "METRICS_NAMESPACE": "CeleryCloud",
    "SERVER_DEBUG_PORT": 5890,
    "DEBUG_HOST": "127.0.0.1",
    "DEBUG_MODE": False,
    "TASKS": {},
}


def clean_env(monkeypatch):
    for var in ALL_VARS:
        monkeypatch.delenv(var, raising=False)


def test_every_default_value(monkeypatch):
    clean_env(monkeypatch)
    s = Settings()
    for name, expected in DEFAULTS.items():
        actual = getattr(s, name)
        assert actual == expected, name
        assert type(actual) is type(expected), name


@pytest.mark.parametrize(
    "name,raw,expected",
    [
        ("CELERY_BACKEND_TABLE", "my-table", "my-table"),
        ("CELERY_BACKEND_REGION", "us-east-2", "us-east-2"),
        ("LOG_LEVEL", "DEBUG", "DEBUG"),
        ("LOG_FORMAT", "{message}", "{message}"),
        ("LOG_ENQUEUE", "true", True),
        ("LOG_DIAGNOSE", "true", True),
        ("CB_FAIL_MAX", "11", 11),
        ("CB_RESET_TIMEOUT", "12", 12),
        ("MAX_ATTEMPTS", "13", 13),
        ("LAMBDA_INVOKE_TIMEOUT", "14", 14),
        ("RESULT_TTL_SECONDS", "7200", 7200),
        ("TIMEOUT_MARGIN_SECONDS", "20", 20),
        ("RESULT_EXTENDED", "true", True),
        ("RESULT_SERIALIZER", "MsgPack", "msgpack"),
        ("BATCH_CONCURRENCY", "4", 4),
        ("INIT_MODULES", "a.b, c ,,d", ["a.b", "c", "d"]),
        ("METRICS_ENABLED", "true", True),
        ("METRICS_NAMESPACE", "MyApp", "MyApp"),
        ("SERVER_DEBUG_PORT", "15", 15),
        ("DEBUG_HOST", "0.0.0.0", "0.0.0.0"),  # nosec: only a test value
        ("DEBUG_MODE", "true", True),
    ],
)
def test_every_setting_reads_its_own_variable(monkeypatch, name, raw, expected):
    clean_env(monkeypatch)
    monkeypatch.setenv(name, raw)
    s = Settings()
    assert getattr(s, name) == expected
    # and only that one changed
    for other, default in DEFAULTS.items():
        if other != name:
            assert getattr(s, other) == default, other


def test_error_messages_are_explicit():
    with pytest.raises(OSError) as exc:
        Settings.get_env_variable("SURELY_NOT_DEFINED_VAR_123")
    assert str(exc.value) == (
        "Environment variable 'SURELY_NOT_DEFINED_VAR_123' "
        "is not defined and does not have default value."
    )
    with pytest.raises(ValueError) as exc:
        Settings._parse_tasks("[]")
    assert str(exc.value) == "Environment variable 'TASKS' must be a JSON object"
    with pytest.raises(ValueError) as exc:
        Settings._parse_tasks('{"a": "nourl"}')
    assert str(exc.value) == (
        "Task 'a' in 'TASKS' must map to a 'scheme://...' url, got 'nourl'"
    )


def test_result_ttl_zero_disables_expiration(monkeypatch):
    assert make(monkeypatch, RESULT_TTL_SECONDS="0").RESULT_TTL_SECONDS == 0


def test_negative_result_ttl_is_rejected(monkeypatch):
    with pytest.raises(ValueError) as exc:
        make(monkeypatch, RESULT_TTL_SECONDS="-1")
    assert str(exc.value) == (
        "Environment variable 'RESULT_TTL_SECONDS' must be 0 (no expiry) "
        "or a positive number of seconds, got -1"
    )


def test_result_ttl_must_be_an_integer(monkeypatch):
    with pytest.raises(ValueError, match="RESULT_TTL_SECONDS"):
        make(monkeypatch, RESULT_TTL_SECONDS="a day")


def test_negative_timeout_margin_is_rejected(monkeypatch):
    with pytest.raises(ValueError) as exc:
        make(monkeypatch, TIMEOUT_MARGIN_SECONDS="-1")
    assert str(exc.value) == (
        "Environment variable 'TIMEOUT_MARGIN_SECONDS' must be >= 0, got -1"
    )


def test_timeout_margin_zero_is_allowed(monkeypatch):
    assert make(monkeypatch, TIMEOUT_MARGIN_SECONDS="0").TIMEOUT_MARGIN_SECONDS == 0


def test_unknown_result_serializer_is_rejected(monkeypatch):
    with pytest.raises(ValueError) as exc:
        make(monkeypatch, RESULT_SERIALIZER="pickle")
    assert str(exc.value) == (
        "Environment variable 'RESULT_SERIALIZER' must be json, msgpack or yaml, "
        "got 'pickle'"
    )


@pytest.mark.parametrize("value", ["0", "-2"])
def test_batch_concurrency_must_be_at_least_one(monkeypatch, value):
    with pytest.raises(ValueError) as exc:
        make(monkeypatch, BATCH_CONCURRENCY=value)
    assert str(exc.value) == (
        f"Environment variable 'BATCH_CONCURRENCY' must be >= 1, got {value}"
    )
