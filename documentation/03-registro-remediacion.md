# Registro de remediación

Fecha: 2026-11-17 · Plan: [`02-plan-remediacion.md`](02-plan-remediacion.md) · Hallazgos: [`01-analisis-calidad.md`](01-analisis-calidad.md)

## Resultado

| Métrica | Antes | Después |
| --- | --- | --- |
| Tests | 31 | **95** (todos OK, 1 s en lugar de 15 s) |
| Cobertura | 94 % (engañosa) | 98 % (la rama de fallo del handler ya está cubierta) |
| `mypy --strict src` | 16 errores | **0** |
| `ruff check src` | 18 errores | **0** |
| `bandit -r src` | 1 (B104) | **0** |
| Bugs críticos C1–C5 | reproducibles | **no reproducibles** (`evidence/verify_findings.py`) |
| `uv build` | OK | OK (el wheel incluye `py.typed`) |
| `docker build` | — | OK, y el handler se importa dentro de la imagen |

## Tareas ejecutadas

| Tarea | Cambios principales | Ficheros |
| --- | --- | --- |
| R1 | `get_env_int`/`get_env_bool` (valor inválido ⇒ error claro al arrancar); validación de `TASKS`; eliminado `MAX_RETRIES`; nuevos `DEBUG_HOST`, `LOG_DIAGNOSE`, `LAMBDA_INVOKE_TIMEOUT`. | `settings.py` |
| R2 | Handler reescrito: `_process_record` por registro (nunca lanza), el lote entero se procesa siempre, `try/finally` para `trace_id`, `batchItemFailures` para fallos de backend. | `runners/aws_lambda.py`, `entities/lambda_response.py` |
| R3 | Estados `STARTED`/`SUCCESS`/`FAILURE`; los fallos se guardan con `exc_type/exc_message/exc_module` y traceback. | `aws_lambda.py`, `task_model.py` |
| R4 | `args`/`kwargs` desde el cuerpo; `retries`/`eta` copiados; `SQSMessage.from_record` y `get_message` lanzan `MessageDecodeException`; campos de `Headers`/`Properties` no usados pasan a opcionales; `Task.eta` tipado. | `entities/` |
| R5 | `get_task` corregido; `_task_key` único (documentada la peculiaridad); serialización con `default=str`; aviso al actualizar tarea inexistente. | `models/task_model.py` |
| R6 | Breaker por ARN que ignora `LambdaFunctionError`; reintentos solo si la función no llegó a ejecutarse; cliente `boto3` cacheado con `read_timeout` configurable y sin reintentos de botocore; ARN validado. | `runners/lambda_strategy.py` |
| R7 | `importlib`; ruta incompleta ⇒ error claro; convención documentada. | `runners/local_strategy.py` |
| R8 | `debugpy` en `127.0.0.1` por defecto; `diagnose=False`; `colorize` automático; sin volcado de eventos/`TASKS`; `print`→logger. | `debug_server.py`, `logging.py`, `aws_lambda.py` |
| R9 | `super().__init__`, `str()` sin `None`, exports. | `exceptions/` |
| R10 | 0 errores de lint/tipos/seguridad; sin importación circular; `py.typed`. | varios |
| R11 | Nuevo `ci.yml`; `release.yml` con quality gate previo, secretos y datos de evento por `env:`, `permissions`, push solo en rama. | `.github/workflows/` |
| R12 | `uv` desde su imagen oficial con versión fijada; `--no-cache-dir`; `.dockerignore` ampliado. | `Dockerfile`, `.dockerignore` |
| R13 | `.PHONY`; licencia SPDX, URLs y clasificadores; ID de cuenta ficticio en `.env.template` y README. | `makefile`, `pyproject.toml` |
| R14 | Tests reescritos/añadidos con una fábrica de eventos SQS reales (`tests/conftest.py`); eliminado el fichero de tests comentado. | `tests/` |
| R15 | README: variables, estados, batch parcial, tareas locales, limitaciones; `CLAUDE.md` actualizado. | `README.md`, `CLAUDE.md` |

## Cambios de comportamiento (leer antes de desplegar)

1. **Estados en el backend**: ahora `STARTED`/`FAILURE` en lugar de `PROCESSING`/`ERROR`. Cualquier consumidor que leyera los antiguos debe actualizarse (los clientes Celery estándar ya esperaban los nuevos).
2. **Respuesta del handler**: incluye siempre `batchItemFailures` (lista, vacía si no hay reintentos). Para que SQS la respete hay que activar `ReportBatchItemFailures` en el *event source mapping*; sin eso se ignora y el comportamiento de borrado de SQS no cambia.
3. **Argumentos desde el cuerpo**: solo se aceptan mensajes con `content-type: application/json`. Un cliente con otro serializador (pickle, yaml) ahora recibe `FAILURE` con "Unsupported content type" en lugar de un fallo opaco.
4. **`debugpy` solo en loopback**: quien lo usara dentro de un contenedor debe fijar `DEBUG_HOST=0.0.0.0` de forma explícita (y proteger el puerto).
5. **Validación estricta de entorno**: valores inválidos (`DEBUG_MODE=maybe`, `CB_FAIL_MAX=cinco`, `TASKS` mal formado) hacen fallar el arranque. Antes se aceptaban y fallaban después, o se interpretaban mal.
6. **Logs**: ya no se vuelcan variables locales en tracebacks (`LOG_DIAGNOSE=true` lo reactiva) ni el evento completo ni `TASKS` en DEBUG.
7. **Lambdas remotas**: los errores devueltos por la función ya **no se reintentan** y no abren el circuito; el timeout de lectura pasa de 60 s (por defecto de boto3) a 900 s (después, por defecto 840 s, para quedar por debajo del máximo del runner).
8. `str(RunnerBaseException("m"))` ahora es `"m"` (antes `"m: None"`); `MAX_RETRIES` desaparece.

## Qué no he podido verificar

- **(Resuelto en `05-verificacion-readme.md`, con AWS simulado)** **Interoperabilidad real con Celery/DynamoDB.** No hay `celery` instalado ni acceso a AWS. Conservé la clave `b'celery-task-meta-<id>'` (comportamiento previo, documentado en `_task_key`) y los nombres de estado/excepción siguen el formato estándar de Celery, pero conviene una prueba de extremo a extremo con un cliente real (`task.get()` sobre una tarea que falla) antes de publicar.
- **Los workflows de GitHub Actions.** Solo se validó que el YAML es correcto; no se ejecutaron.
- **`batchItemFailures` en AWS.** Se prueba la respuesta, no la reentrega real de SQS.

## Decisiones del propietario (ronda 2) y ejecución

Las siete decisiones pendientes se aprobaron una a una y están ejecutadas.

| # | Decisión aprobada | Implementación | Verificación |
| --- | --- | --- | --- |
| 1 | Descartar duplicados de SQS | `insert_task` con escritura condicional (`attribute_not_exists`); `DuplicateTaskException`; el handler responde `skipped_messages`/`skipped_tasks` y no reentrega. | Test de integración + mutación (quitar la condición ⇒ el test falla). |
| 2 | Resultado demasiado grande ⇒ `FAILURE` claro | `MAX_RESULT_BYTES` (380 000) y `ResultTooLargeException`; se guarda como `FAILURE` y **no** se reentrega. | Test de integración con un resultado de 380 001 bytes. |
| 3 | Respetar `ignore_result` y `expires` | `Task.ignore_result`/`Task.expires`/`is_expired()`; sin escritura en backend si `ignore_result`; tarea caducada ⇒ `REVOKED` sin ejecutarse. `eta` queda como limitación documentada. | Tests de integración (pasada, futura, sin escritura). |
| 4 | Versionado con `uv version` | `makefile`: `build`/`docker-build` ya no suben versión; `bump-version` explícito. `release.yml`: `uv version --bump patch` y commit de `pyproject.toml` **y `uv.lock`**. | Probado en una copia temporal: sube ambos ficheros y `uv lock --check` pasa. El workflow no se pudo ejecutar. |
| 5 | Acciones fijadas por SHA | `checkout` v4.4.0, `setup-uv` v5.4.2, `setup-python` v5.6.0 con comentario de versión. | SHA verificados contra la API de GitHub (el commit existe y el tag apunta a él). |
| 6 | Solo Dependabot | `.github/dependabot.yml` (`uv` y `github-actions`, semanal). Sin `pip-audit`. | YAML válido. |
| 7 | Tests con `moto` (solo DynamoDB + handler) | `moto[dynamodb]` como dependencia de desarrollo; `tests/integration/test_backend_flow.py` (11 tests). | Con mutaciones: reintroducir el bug de `get_task` hace fallar 9 tests; quitar la escritura condicional, 1. |

Resultado final tras esta ronda: **106 tests OK**, `ruff`, `mypy --strict` y `bandit` con 0 hallazgos.

### Efectos a tener en cuenta de estas decisiones

- Un runner que muere con una tarea en `STARTED` deja la tarea en ese estado: la reentrega de SQS se descarta como duplicado (limitación aceptada en la decisión 1; el cliente debe tener timeout).
- Reenviar una tarea con un `task_id` ya usado se trata como duplicado.
- La CI de `release.yml` ahora hace commit de `uv.lock` además de `pyproject.toml`.
- `make release` ya no sube la versión: hay que ejecutar `make bump-version` antes, o dejar que lo haga la CI.

## Pendiente

| Hallazgo | Recomendación |
| --- | --- |
| `eta`/`countdown` | Funcionalidad nueva: `DelaySeconds` de SQS (máx. 15 min) o Step Functions para plazos mayores. |
| Pruebas de extremo a extremo con Celery y AWS reales | Siguen sin hacerse; los tests con `moto` no cubren la interoperabilidad con el cliente Celery real. |
| Lambda remota con `moto` | Descartado por fragilidad (requiere Docker). |
| `pip-audit` | Descartado por el propietario (se mantiene solo Dependabot). |

## Ronda 3: huecos de cobertura

Cobertura de 97 % a **99 %** (con ramas), 106 → **126 tests**. Al cubrir los huecos apareció un defecto nuevo:

- **Código inalcanzable en `SQSMessage.get_task`**: `except ValueError` iba antes que `except ValidationError`, y `ValidationError` de pydantic hereda de `ValueError`, así que los errores de validación perdían su mensaje específico (`"ValidationError getting task"`). Corregido reordenando las ramas; test de regresión añadido.

Tests nuevos: `is_expired` (zonas horarias, fecha sin zona, fecha mal formada), errores `PutError` (duplicado frente a otros errores de backend), `body_encoding` distinto de base64 y los `except` genéricos de `get_task` y `from_lambda`.

Sin cubrir a propósito: `debug_server.py` líneas 11-18 (arranque de `debugpy`, requiere un cliente de depuración) y dos ramas parciales de `aws_lambda.py`.
