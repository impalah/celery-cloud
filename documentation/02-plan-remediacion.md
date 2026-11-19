# Plan de remediación

Orden de ejecución: primero lo que corrompe datos o bloquea clientes, luego seguridad, después robustez y mantenimiento. Cada tarea indica los hallazgos que resuelve ([`01-analisis-calidad.md`](01-analisis-calidad.md)).

## Tareas a ejecutar

| Tarea | Descripción | Resuelve |
| --- | --- | --- |
| **R1** | Configuración tipada: `get_env_int` / `get_env_bool` (rechazan valores inválidos), validación de `TASKS` al arrancar, eliminar `MAX_RETRIES` (sin uso), nuevos ajustes `DEBUG_HOST`, `LOG_DIAGNOSE`, `LAMBDA_INVOKE_TIMEOUT`. | C2, M11 |
| **R2** | Reescribir el handler: procesamiento **por registro** aislado, nunca devuelve `None`, `try/finally` para el `trace_id`, respuesta `batchItemFailures` para fallos de backend, y registro de fallos de ejecución en el backend. | C1, H2, M5 |
| **R3** | Estados compatibles con Celery (`STARTED`, `SUCCESS`, `FAILURE`) y payload de excepción estándar (`exc_type`, `exc_message`, `exc_module`) + `traceback`. | C3 |
| **R4** | Decodificar `args`/`kwargs` desde el **cuerpo** del mensaje; rellenar `retries`/`eta`; `SQSMessage.from_record` que lanza `MessageDecodeException`; relajar los campos de `Headers`/`Properties` que el runner no usa; arreglar `Task.eta`. | C4, M1, M2, M3 |
| **R5** | `TaskModel`: corregir `get_task`, helper único para la clave, serialización tolerante (`default=str`), log de aviso al actualizar una tarea inexistente. | C5, M7, M8, M13 |
| **R6** | Estrategia Lambda: breaker **por función** que no cuenta errores de negocio, reintentos solo ante errores de infraestructura (no `FunctionError`), cliente `boto3` cacheado con timeout configurable y sin reintentos propios de botocore, validación del ARN. | H3, H4, M4 |
| **R7** | Estrategia local: `importlib`, validación de `function`, documentar la convención de llamada. | M12 |
| **R8** | Seguridad de depuración y logs: `debugpy` en `127.0.0.1` por defecto, `diagnose=False` por defecto, `colorize` automático, no volcar eventos/`TASKS` en DEBUG, `print`→logger. | H1, H6, L10 |
| **R9** | Excepciones: `super().__init__`, `__str__` sin `None`, exportar la base y `MessageDecodeException`. | M10 |
| **R10** | Calidad estática: 0 errores en `mypy --strict`, `ruff` y `bandit`; eliminar la importación circular; añadir `py.typed`; tipar `TaskRoute.query`. | L1–L4 |
| **R11** | CI: workflow de CI (lint + tipos + bandit + tests) y la publicación pasa a depender de los tests; secretos y datos de evento por `env:`; `permissions` mínimos. | H5 |
| **R12** | `Dockerfile` y `.dockerignore`: `uv` copiado desde su imagen oficial con versión fijada (sin `curl \| sh`), `--no-cache-dir`, exclusiones. | H7, L7 |
| **R13** | Empaquetado/entorno: `.PHONY` en el `makefile`, metadatos de `pyproject.toml`, ID de cuenta AWS ficticio en `.env.template` y README. | L5 (parcial), L6, L9 |
| **R14** | Tests: reescribir los que fijaban comportamiento erróneo, borrar el fichero comentado, añadir tests de la rama de fallo, `settings`, decodificación del cuerpo, breaker por función, etc. | L8 |
| **R15** | Documentación: README (variables nuevas, semántica de fallos, `ReportBatchItemFailures`, convención de tareas locales) y este registro. | L11 |

## Aplazado (no se ejecuta ahora) y motivo

| Hallazgo | Motivo |
| --- | --- |
| M6 Idempotencia ante duplicados SQS | Requiere decidir una política (escritura condicional + qué hacer con un duplicado en curso/terminado) y probar contra DynamoDB real. Es una decisión de diseño del propietario. |
| M9 Límite de 400 KB por ítem | Requiere decidir dónde desbordar (S3, truncado…). Se documenta. |
| M14 `eta`/`expires`/`ignore_result` | Son funcionalidad nueva (aplazar mensajes, descartar caducados), no corrección. Se documenta como limitación conocida. |
| L5 sustituir `bump2version`, doble bump con CI | Toca el proceso de publicación y no puedo probarlo aquí; decisión del propietario. |
| H5 fijar acciones por SHA | Requiere resolver SHAs actuales en GitHub; recomendado, pero no verificable offline. |
| Auditoría de vulnerabilidades (`pip-audit`) en CI | Se recomienda añadirla cuando exista el workflow de CI estable. |

## Criterios de aceptación

- `pytest` en verde, sin avisos.
- `mypy --strict src`: 0 errores · `ruff check src`: 0 errores · `bandit -r src`: 0 hallazgos.
- El script `documentation/evidence/verify_findings.py` deja de reproducir C1–C5.
