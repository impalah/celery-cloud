# Registro de la implementación de paridad con Celery

Fecha: 2026-11-17 · Plan: [`06-plan-paridad-celery.md`](06-plan-paridad-celery.md) · Decisiones del propietario: sección 7 del plan.

## Resultado

Se ejecutaron las cinco fases del plan, con las decisiones D1-D8 y la del S3 (aplazado, los resultados > 400 KB siguen siendo `FAILURE`).

| Métrica | Antes (`05`) | Después |
| --- | --- | --- |
| Tests | 198 | **505** |
| Cobertura (con ramas) | 99 % | **99 %** (lo no cubierto: arranque de `debugpy` y 4 ramas parciales de `aws_lambda.py`) |
| `ruff`, `mypy --strict`, `bandit` | 0 | 0 |
| Módulos nuevos | | `deadline`, `tasks`, `runtime`, `signals`, `metrics`, `messaging`, `serialization`, `client`, `runners/canvas`, `runners/builtin_tasks`, `models/canvas_model` |
| Versión | 0.2.0 | 0.2.0 (decisión D3) |

## Qué hace ahora el runner (frente al punto de partida del plan)

| Prueba con Celery 5.7 real | Antes | Ahora |
| --- | --- | --- |
| `group` | funciona | funciona |
| `chain`, `chord`, `link`, `link_error` | **no funcionaban** | funcionan (`phase23_check.py`) |
| `map`, `starmap`, `chunks` | no | funcionan (`phase4_map_check.py`) |
| Excepción `ValueError` en la tarea | el cliente recibía `TaskExecutionException` | el cliente recibe `ValueError` |
| `countdown` / `eta` | ignorado | respetado (saltos de SQS de 15 min) |
| Reintentos (`self.retry`, `autoretry_for`, backoff) | no | sí, con `@celery_cloud.task` |
| `update_state` / estados propios (`PROGRESS`) | no | sí |
| `soft_time_limit` / `time_limit` y plazo de Lambda | tarea atascada en `STARTED` | `FAILURE` con `SoftTimeLimitExceeded`/`TimeLimitExceeded` antes de que AWS mate la función |
| `revoke` | sin efecto | funciona con `celery_cloud.client.install(app)` (opcional) |
| msgpack, yaml, compresión gzip/bzip2/lzma | no | sí |
| Señales, `on_success/on_failure/on_retry`, métricas EMF | no | sí |
| Concurrencia dentro del lote | no | `BATCH_CONCURRENCY` |

## Tareas ejecutadas

| Fase | Tareas | Verificación con el cliente real |
| --- | --- | --- |
| 1 | P1.1 excepción original, P1.2 plazos con `SIGALRM`, P1.3 metadatos (`RESULT_EXTENDED`), P1.4 test de `group` | `phase1_check.py` |
| 2 | P2.1-P2.3 `@task`, `TaskContext`, `Ignore`/`Reject`/`Retry` | `phase23_check.py` |
| 3 | P3.1 `eta`, P3.2 reintentos (toma de control con el atributo `attempt`), P3.3 **solo documentación** (D6) | `phase23_check.py` |
| 4 | P4.1 `link`/`link_error`, P4.2 `chain`, P4.3 `chord`, `map`/`starmap`/`chunks` | `phase23_check.py`, `phase4_map_check.py` |
| 5 | P5.1 `revoke` (cliente), P5.2 concurrencia, P5.3 serializadores y compresión, P5.4 hooks y señales, P5.5 métricas, P5.6-5.7 documentación | `phase5_check.py` |

Los scripts están en `documentation/evidence/e2e/` (`runner_loop.py` emula el *event source mapping*, incluida la reentrega de `batchItemFailures`).

## Defectos encontrados al probar con el cliente real

Los tests unitarios con mocks no los habrían detectado.

1. **La compresión `gzip` de kombu es zlib.** Con `task_compression="gzip"` el cliente envía `application/x-gzip`, pero el contenido es un flujo zlib, no un `.gz`. El primer intento (`gzip.decompress`) dejaba la tarea sin procesar. Ahora `application/x-gzip` se descomprime con detección automática de cabecera (zlib o gzip).
2. **`countdown` de 6 s se ejecutaba a los 5 s** (el retraso se truncaba). Ahora se redondea hacia arriba: una tarea nunca se ejecuta antes de su `eta`.
3. **El emulador del *event source mapping* borraba todos los mensajes**, incluso los de `batchItemFailures`. No era un defecto del runner, pero ocultaba el comportamiento de `Reject(requeue=True)`: se corrigió el emulador.
4. **Los `soft_time_limit`/`time_limit` del decorador no se aplicaban** (solo los del mensaje). El runner ahora lee las opciones de la función antes de ejecutarla; el límite del cliente gana al del decorador.

## Decisiones de diseño y sus compromisos

- **Reintentos con el mismo `task_id`**: el registro condicional anti-duplicados ya no basta. El elemento guarda el atributo extra `attempt` (solo si hubo reintento, así que el formato de Celery no cambia en el caso normal); un mensaje con `retries` mayor toma la tarea con una actualización condicional.
- **Atributos extra, no estándar de Celery** (ignorados por el cliente): `attempt`, `revoked`.
- **Chord**: se replica el protocolo del backend DynamoDB de Celery (`celery-taskset-meta-<gid>` para los ids del grupo y `chord-unlock-<gid>` con `chord_count`), leído del código fuente y de los elementos reales que escribe el cliente. El cuerpo recibe **un** argumento: la lista de resultados, en orden de grupo.
- **`link_error`** en estilo antiguo (recibe el `uuid`), por D5.
- **Fallos al enviar los mensajes siguientes** (callbacks, cadena): la tarea conserva su `SUCCESS` y el fallo solo se registra en el log; el callback se pierde. Es el compromiso para no duplicar la ejecución al reentregar.
- **Los límites de tiempo usan `SIGALRM`**: solo en el hilo principal; con `BATCH_CONCURRENCY` > 1 no se pueden interrumpir tareas, solo se comprueba el margen antes de empezar cada registro.
- **`pickle`, brotli y zstd** se rechazan; el resultado se escribe con `RESULT_SERIALIZER` (debe coincidir con el `result_serializer` del cliente); no hay compresión de resultados.

## Qué no se verificó

- **Nada contra AWS real** (SQS, DynamoDB, Lambda, EventBridge Scheduler, IAM): todo con `moto` y un cliente Celery real. En concreto: los límites reales de `DelaySeconds`, el borrado por TTL, los permisos IAM nuevos (`sqs:SendMessage`, `dynamodb:DeleteItem`) y los comandos de `aws scheduler` de `periodic-tasks.rst`.
- **`SIGALRM` dentro del tiempo de ejecución de Lambda**: el handler se ejecuta en el hilo principal en el runtime de Python, pero no se probó en AWS.
- **`ctx.is_revoked()` y consistencia**: se lee con lectura consistente; no se midió el coste en DynamoDB.
- **Chord con cadenas dentro, grupos anidados, `chord` de `chord`**: no probados.
- **`link_error` de nuevo estilo** (`(request, exc, traceback)`): no se usa.

## Documentación

- `pages_source/`: `concepts`, `configuration`, guía de usuario (nuevas páginas `server-task-api`, `client-retries-progress`, `client-canvas`, `client-revoke`), infraestructura (`periodic-tasks`, `queues-and-priorities`, IAM y operaciones actualizados) y API (tareas, señales, cliente, canvas, mensajería, serialización, plazos).
- Los ejemplos nuevos (`jobs.py`, `signals_setup.py`, `canvas.py`, `retries_and_progress.py`, `revoke.py`) se ejecutaron con el cliente real; los del servidor además los cubre `tests/integration/test_docs_examples.py`.

## Verificación en AWS real (2026-11-19)

Cuenta `<id de la cuenta>`, profile `default`, región `eu-central-1`, entorno `test` (recursos `celery-cloud-test-*`). Estado de Terraform **local** (`infra/terraform/stacks/example/terraform.tfstate`, fuera de git) mediante un `local_backend_override.tf` temporal.

**Despliegue** (`infra/terraform/stacks/example`): primer `apply` con 7 recursos (cola y DLQ, política de redrive, tabla DynamoDB, repositorio ECR, política del cliente); imagen construida con el `Dockerfile` del repositorio más las tareas de ejemplo y subida a ECR; segundo `apply` con 5 recursos (rol, política, grupo de logs, función, *event source mapping*). `plan` y `apply` salieron a la primera, sin cambios por corregir en el código de Terraform.

**Pruebas con el cliente Celery real** (los ejemplos de `pages_source/examples/client/`):

| Ejemplo | Resultado |
| --- | --- |
| `basic.py` | 18, `SUCCESS` (4 s con arranque en frío) |
| `errors.py` | `ValueError` original en el cliente; `ZeroDivisionError`; sondeo de estados |
| `structured.py` | modelo pydantic de ida y vuelta |
| `canvas.py` | `link`, `chain`, `group`, `chord`, `link_error`, `starmap`, `chunks`: todo correcto en 6 s |
| `retries_and_progress.py` | reintentos con retraso, `autoretry_for` con backoff, `PROGRESS`, `soft_time_limit` (parte parcial por `SIGALRM`), `countdown=10` (ejecutado a los 10 s) |
| `revoke.py` | tarea retenida revocada (`REVOKED`); tarea en ejecución detenida cooperativamente tras 7 pasos |

**Observado:** colas y DLQ vacías al terminar; sin errores de permisos en los logs; métricas EMF escritas (`TaskSucceeded`, `TaskFailed`, `TaskDuration`...); 104 MB de memoria usada de 512; arranque en frío (`Init Duration`) de 1,7 s.

**Queda verificado en real:** los comandos y permisos IAM del rol del runner (incluidos `sqs:SendMessage` y `dynamodb:DeleteItem`), `DelaySeconds` y el reenvío para `eta`, `SIGALRM` en el runtime de Lambda, la conexión del *event source mapping* y el código Terraform.

**Sigue sin verificar:** la reentrega real de `batchItemFailures` (el mapping se creó con `ReportBatchItemFailures`, pero no se provocó ningún fallo de lote), el borrado por TTL, el paso a la DLQ tras `maxReceiveCount`, tareas `lambda://` contra una función remota, EventBridge Scheduler, y los diagramas Mermaid publicados.

### EventBridge Scheduler (2026-11-19, mismo entorno)

Se añadió el módulo `infra/terraform/modules/schedules` (grupo, rol, DLQ y una programación por entrada de la variable `schedules`; el mensaje Celery se construye en Terraform) y `stacks/example/06.schedules.tf`. Probado en real con tres programaciones:

- **Defecto encontrado:** la condición `aws:SourceArn` del rol del scheduler hacía fallar `CreateSchedule` (`The execution role you provide must allow AWS EventBridge Scheduler to assume the role`); y el provider tardó minutos en rendirse. Se dejó solo `aws:SourceAccount`.
- `rate(1 minute)` con `ignore_result=true`: la tarea se ejecutó **en cada tick** (12:33, 12:34, 12:34, 12:35...).
- `rate(1 minute)` con `ignore_result=false`: se ejecutó **solo el primero**; los siguientes se descartaron como duplicados (mismo `task_id`). Es lo que documenta `periodic-tasks.rst`.
- Programación `cron(...)` con zona horaria creada en `DISABLED`; las dos de cada minuto se eliminaron después con `apply` (también verificado).
- Comandos manuales de `periodic-tasks.rst` (rol con su política de confianza, `create-schedule` con `rate`, y con `cron`+zona horaria): ejecutados tal cual; la tarea corrió. Se añadió a la página la creación del rol (antes solo un comentario).
- **DLQ del scheduler verificada:** una programación `at(...)` hacia una cola inexistente (sin reintentos) dejó el mensaje en `celery-cloud-test-schedules-dlq` con `ERROR_CODE=AWS.SimpleQueueService.NonExistentQueue`, `EXHAUSTED_RETRY_CONDITION=MaximumRetryAttempts` y el `Input` original; la programación se autoeliminó (`ActionAfterCompletion=DELETE`).
- No se probó un `cron` con zona horaria que dispare de verdad.
