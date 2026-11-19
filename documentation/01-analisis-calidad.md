# Análisis de calidad de `celery-cloud`

Fecha: 2026-11-17 · Versión analizada: 0.1.29 (rama `main`, commit `32b30bd` + dependencias actualizadas)

## 1. Alcance y método

Se revisó el 100 % del código (`src/`, 998 líneas), los tests (`tests/`), el empaquetado (`pyproject.toml`, `makefile`, `Dockerfile`, `.dockerignore`), la CI (`.github/workflows/release.yml`) y el README.

Herramientas ejecutadas (todas con las dependencias ya actualizadas):

| Herramienta | Resultado inicial |
| --- | --- |
| `pytest` | 31 tests OK, cobertura 94 % |
| `mypy --strict src` | **16 errores** |
| `ruff check src` | **18 errores** (13 autocorregibles) |
| `bandit -r src` | 1 hallazgo medio (B104) |
| Revisión manual | ver hallazgos |

Los hallazgos marcados **[VERIFICADO]** se reprodujeron con un script (`documentation/evidence/verify_findings.py`) y no son hipótesis.

> **Aviso sobre la cobertura:** el 94 % es engañoso. Las líneas sin cubrir de `aws_lambda.py` (127-135) son precisamente la rama de fallo, y varios tests simulan la entrada con el formato que el código *espera* (no el real), de modo que ocultan bugs (ver C5).

Escala de severidad: **Crítica** (pérdida de datos / fallo funcional grave), **Alta** (seguridad o fiabilidad en producción), **Media** (bug latente o robustez), **Baja** (calidad, mantenimiento).

---

## 2. Hallazgos

### Críticos

**C1 · El handler devuelve `None` y pierde mensajes cuando una tarea falla** [VERIFICADO]
`runners/aws_lambda.py:158-171`. El `except (MessageDecodeException, TaskDecodeException, BackendException, TaskExecutionException)` añade un `FailedTask` y **no hace `return`**: la función termina devolviendo `None`.
Consecuencias, reproducidas con un lote de 3 mensajes donde el primero falla:
1. Los mensajes 2 y 3 **nunca se procesan** (el `for` está dentro del `try`).
2. Como la función termina sin excepción, SQS **borra los 3 mensajes**: se pierden.
3. La tarea 1 queda en estado `PROCESSING` para siempre (nadie la actualiza).
4. `trace_id_context` no se limpia.
Además `record` puede no estar definido en ese `except` (`NameError`) si la excepción se produce antes del primer registro.

**C2 · Las variables de entorno numéricas/booleanas llegan como `str`** [VERIFICADO]
`settings.py`. `get_env_variable` devuelve `os.getenv(...)`, que es siempre `str` cuando la variable existe; el valor por defecto (int/bool) enmascara el problema solo si la variable *no* está definida.
- `CB_FAIL_MAX="3"` → `pybreaker` lanza `TypeError: '>=' not supported between 'int' and 'str'` en el primer fallo. Igual con `MAX_ATTEMPTS` (`tenacity`).
- `DEBUG_MODE="false"` es **truthy** → se activa `debugpy` y `wait_for_client()` bloquea el arranque. Mismo problema con `LOG_ENQUEUE="False"`.
- `SERVER_DEBUG_PORT` llega como `str`.

**C3 · Se escriben estados que Celery no entiende (`PROCESSING`, `ERROR`) y los fallos nunca se registran como `FAILURE`**
`runners/aws_lambda.py`, `models/task_model.py`. Los estados válidos de Celery son `PENDING/RECEIVED/STARTED/SUCCESS/FAILURE/REVOKED/REJECTED/RETRY/IGNORED`. Con `PROCESSING`/`ERROR`, `AsyncResult.ready()` nunca es verdadero para una tarea fallida: **el cliente se queda esperando indefinidamente** (el propio ejemplo del README hace polling con `task.ready()`). Además las excepciones de ejecución (C1) ni siquiera actualizan el estado.

**C4 · Los argumentos se leen de `argsrepr`/`kwargsrepr` en lugar del cuerpo del mensaje** [VERIFICADO]
`entities/sqs_entities.py:get_task`. Celery fija esas cabeceras a una *representación textual truncada* (por defecto 1024 caracteres, termina en `...`) pensada para logs. Los argumentos reales viajan en el cuerpo (`[args, kwargs, embed]`). Resultado:
- Argumentos largos → `TaskDecodeException` (la tarea falla) o, peor, datos truncados.
- Argumentos no literales (`datetime`, `Decimal`, `UUID`…) → `ast.literal_eval` falla.
`decode_body()` ya existe pero **no se usa**.

**C5 · `TaskModel.get_task` no puede leer lo que escribe `update_task`** [VERIFICADO]
`models/task_model.py:151`. `insert/update` guardan JSON en bruto en un `BinaryAttribute(legacy_encoding=False)`; `get_task` hace `base64.b64decode` sobre ese JSON → `BackendException: Invalid base64-encoded string`. El test existente (`test_get_task_success`) codifica el dato en base64 *a mano*, por eso pasa: **el test valida el bug**.

### Altos

**H1 · `debugpy` escucha en `0.0.0.0` sin autenticación** (bandit B104) · `debug_server.py:9`. Quien alcance el puerto 5890 obtiene ejecución remota de código. Debe escuchar en `127.0.0.1` por defecto y ser configurable de forma explícita.

**H2 · Sin respuesta parcial de lote (`batchItemFailures`)**. Con la mapping de SQS, devolver sin excepción borra *todo* el lote. No hay forma de pedir reentrega solo de los mensajes cuyo backend falló.

**H3 · Un único circuit breaker global para todas las Lambdas remotas** · `runners/lambda_strategy.py:13`. Si una Lambda destino falla 5 veces, el circuito se abre para **todas** las tareas remotas. Además los errores de negocio (`FunctionError`) cuentan como fallo del breaker.

**H4 · Política de reintentos peligrosa en la invocación remota** · `lambda_strategy.py:22-27`.
- Se reintenta ante cualquier `TaskExecutionException`, incluido `FunctionError`, es decir, cuando la función **sí se ejecutó** y falló: reejecuta código con efectos secundarios hasta 5 veces.
- `boto3` usa `read_timeout=60 s` por defecto y reintenta por su cuenta ante timeouts: una Lambda de >60 s se **reinvoca mientras sigue ejecutándose**, y encima tenacity reintenta otra vez (reintentos multiplicados).
- 5 intentos con espera exponencial pueden superar el timeout de la propia Lambda runner.

**H5 · Pipeline de publicación inseguro** · `.github/workflows/release.yml`.
- Publica en PyPI en cada push a `main` **sin ejecutar tests ni lint** (el paso de tests está comentado).
- `${{ github.event.release.body }}` y `${{ secrets.PYPI_TOKEN }}` se interpolan directamente en scripts `run:` (patrón de inyección de comandos / exposición de secretos).
- Sin bloque `permissions:` (token con permisos por defecto).
- `git push origin HEAD` falla en el evento `release` (HEAD desacoplado).
- Acciones fijadas por tag mutable, no por SHA.

**H6 · Posible fuga de datos en logs** · `logging.py`, `aws_lambda.py`. `diagnose=True` hace que loguru vuelque **los valores de las variables locales** en los tracebacks (incluidos argumentos de tarea, potencialmente sensibles). Además, a nivel DEBUG se vuelca el evento completo y `settings.TASKS` (ARNs).

**H7 · Cadena de suministro del `Dockerfile`**. `curl … | sh` para instalar `uv` sin versión ni checksum, y `dnf install tar gzip` solo para eso; imagen base sin fijar; `pip install` sin `--no-cache-dir`.

### Medios

| ID | Hallazgo | Ubicación |
| --- | --- | --- |
| M1 | `MessageDecodeException` **nunca se lanza**. `SQSRecord.get_message()` propaga `JSONDecodeError`/`binascii.Error`, y el handler indexa `message["body"]` etc. sin validar (`KeyError`, `ValidationError` sin envolver). | `sqs_entities.py:299`, `aws_lambda.py:104` |
| M2 | `Task.eta: str = Field(default=None)` es un tipo incorrecto (error de mypy). `retries` y `eta` de las cabeceras no se copian a `Task`. | `entities/task.py:56` |
| M3 | Los modelos `Headers`/`Properties` exigen campos que no usa el runner (`stamps`, `replaced_task_nesting`, `ignore_result`, `origin`, `root_id`, `timelimit`…); mensajes de clientes Celery más antiguos/otros serializadores se rechazan innecesariamente. | `sqs_entities.py` |
| M4 | Se crea un cliente `boto3` por invocación; `route.module.split(":")[3]` lanza `IndexError` con un ARN mal formado; no se valida el ARN. | `lambda_strategy.py:29-31` |
| M5 | `trace_id_context` se limpia manualmente en cada rama en lugar de `finally`. | `aws_lambda.py` |
| M6 | SQS es *at-least-once*: un mensaje duplicado re-ejecuta la tarea y `insert_task` **sobrescribe** el estado existente (`save()` sin condición). | `task_model.py:60` |
| M7 | `update_task` sobre una tarea inexistente devuelve `None` en silencio: el resultado se pierde sin log. | `task_model.py:126` |
| M8 | `json.dumps(task_result.model_dump())` falla con resultados no serializables (`datetime`, `Decimal`, `bytes`…) **después** de haber ejecutado la tarea; la tarea se reporta como fallida aunque se ejecutó. | `task_model.py:63, 108` |
| M9 | Sin control del límite de 400 KB por ítem de DynamoDB para resultados grandes. | `task_model.py` |
| M10 | `RunnerBaseException.__init__` no llama a `super().__init__` (`e.args` vacío, no picklable); `str()` imprime `"mensaje: None"` sin detalle. `MessageDecodeException` y la base no se exportan. | `exceptions/` |
| M11 | `TASKS` con JSON inválido o valores incorrectos revienta al importar con un error opaco; `MAX_RETRIES` está definido y **no se usa**. | `settings.py` |
| M12 | Estrategia local: usa `__import__` (en vez de `importlib`), no valida `function` vacío (`task://modulo`), y la convención `function(args, kwargs)` (dos parámetros posicionales, no `*args/**kwargs`) no está documentada. | `local_strategy.py` |
| M13 | La clave `str(b"celery-task-meta-…")` (resulta en el literal `"b'celery-task-meta-…'"`) está repetida 3 veces y es una peculiaridad del backend DynamoDB de Celery sin documentar. | `task_model.py` |
| M14 | Cabeceras ignoradas: `eta`/`countdown` (la tarea se ejecuta de inmediato), `expires`, `ignore_result`. | handler |

### Bajos / mantenibilidad

| ID | Hallazgo |
| --- | --- |
| L1 | 16 errores de `mypy --strict`, 18 de `ruff` (imports sin usar en `aws_lambda.py`, imports desordenados, líneas largas). |
| L2 | Importación circular: `sqs_entities.py` hace `from celery_cloud.entities import Task` (el paquete que lo está importando). |
| L3 | Sin `py.typed`: pese a usar mypy estricto, los consumidores no ven los tipos. |
| L4 | `TaskRoute.query: dict` sin parametrizar y nunca utilizado. |
| L5 | `makefile` sin `.PHONY` (un directorio `build/` haría que `make build` no se ejecute); `build`/`release`/`docker-build` **suben la versión** como efecto colateral y la CI vuelve a subirla (doble bump); `bump2version` está abandonado. |
| L6 | El ID de cuenta AWS `670089840758` está en `.env.template` y `README.md`. |
| L7 | `.dockerignore`: el patrón `.env/` no excluye el fichero `.env`; no excluye `tests/`. (Hoy el `Dockerfile` solo copia `src/`, así que no hay fuga real.) |
| L8 | Tests: muy basados en *mocks* que ocultan bugs (C5), parchean `builtins.__import__`, tienen un test comentado y un fichero entero (`test_aws_lambda_runner.py`) comentado, sin tests de la rama de fallo del handler, de `settings` ni de `debug_server`. Un test fija el comportamiento defectuoso `"…: None"`. |
| L9 | `pyproject.toml`: `license = {text=…}` en formato obsoleto (PEP 639), sin `[project.urls]`, sin clasificador de Python 3.12. `debug_server` se publica en el paquete pero `fastapi/debugpy/uvicorn` son solo dev. |
| L10 | `print` en `debug_server.py` en lugar del logger; docstrings con `_description_`; formato de Pydantic inconsistente (`default = None`). |
| L11 | README incompleto: secciones vacías ("Using local tasks"), enlace de imagen sin URL, variables `CB_*`/`MAX_ATTEMPTS`/`LOG_*` sin documentar. |

### Puntos positivos (no tocar)

- El enrutado es una **lista blanca** definida por entorno (`TASKS`): un mensaje no puede elegir qué módulo se importa ni qué ARN se invoca. No hay inyección por mensaje.
- Se usa `ast.literal_eval` (no `eval`) y validación Pydantic en las entidades.
- No hay secretos en el repositorio; `.env` está en `.gitignore`.
- Arquitectura limpia (Strategy para los ejecutores, excepciones de dominio, singleton de settings).

---

## 3. Resumen por severidad

| Severidad | Nº |
| --- | --- |
| Crítica | 5 |
| Alta | 7 |
| Media | 14 |
| Baja | 11 |

El plan de remediación está en [`02-plan-remediacion.md`](02-plan-remediacion.md).
