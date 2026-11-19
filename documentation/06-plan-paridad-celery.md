# Plan: paridad funcional con un worker de Celery

Fecha: 2026-11-17 · Estado: **decisiones tomadas (sección 7), implementación en curso por fases** (ver `07-registro-paridad.md`).

## 1. Objetivo y principios

Cerrar, **siempre que sea viable en AWS Lambda**, la diferencia entre este runner y un worker de Celery, sin romper lo que ya funciona.

1. **El cliente sigue siendo Celery estándar.** Ninguna fase obliga a cambiar el código de la aplicación cliente, salvo las que se marquen como "opcional" (y esas lo dicen).
2. **Sin Celery en el runner**, salvo que se decida lo contrario en la decisión D2.
3. **Compatibilidad hacia atrás del contrato de tareas**: las funciones `f(args, kwargs)` actuales siguen funcionando. Lo nuevo es opt-in.
4. **Cada fase se verifica con un cliente Celery real** contra `moto` (el procedimiento de `documentation/evidence/e2e/`), no solo con tests unitarios: los tests con mocks ya ocultaron bugs reales en esta auditoría.
5. Lo que no sea viable o no convenga se documenta como limitación, con el motivo (sección 4).

## 2. Punto de partida medido

Prueba con Celery 5.7.0 real y el runner actual (`documentation/evidence/e2e/spike_paridad.py`, ejecutada el 2026-11-17):

| Prueba | Resultado |
| --- | --- |
| `group(add.s(1,2), add.s(3,4))` | **Funciona**: `[3, 7]` (cada tarea es un mensaje independiente) |
| `chain(add.s(1,2), add.s(10))` | **No funciona**: el primer paso termina (`SUCCESS`, 3); el segundo **nunca se envía**; `chain.state` queda `PENDING` para siempre |
| `chord([add.s(1,2), add.s(3,4)])(subtract.s())` | **No funciona**: la cabecera termina (`SUCCESS`, `SUCCESS`); el cuerpo nunca se ejecuta |
| Excepción en una tarea (`ValueError`) | El cliente recibe `TaskExecutionException`, **no** `ValueError` (el tipo original se pierde) |
| `add.apply_async(countdown=20)` | Se ejecuta a los 0,5 s: `countdown`/`eta` se ignoran |

Esto es lo que el worker de Celery hace y el runner no: callbacks (`link`, `chain`, `chord`) los despacha el worker al terminar la tarea, a partir del campo `embed` del mensaje, que el runner no lee.

## 3. Inventario: qué tiene Celery y qué podemos hacer

Leyenda de viabilidad: **Sí** (encaja bien en Lambda), **Parcial** (con límites que se documentan), **No** (ver sección 4). Esfuerzo: S ≤ 0,5 día, M 1-2 días, L 3-5 días (incluye tests con cliente real y documentación).

| # | Característica de Celery | Hoy | Viabilidad | Enfoque | Esf. | Fase |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Tipo de excepción original en el cliente (`except ValueError`) | Se pierde (`TaskExecutionException`) | Sí | Escribir `exc_type`/`exc_module` de la excepción original (Celery reconstruye la clase en el cliente, o crea una dinámica si no puede importarla) | S | 1 |
| 2 | `time_limit` / `soft_time_limit` | Ignorados; un timeout de Lambda deja la tarea en `STARTED` | Sí | Usar `context.get_remaining_time_in_millis()` y `SIGALRM`: `SoftTimeLimitExceeded` y fallo registrado **antes** de que AWS mate la función | M | 1 |
| 3 | Metadatos de resultado (`worker`, `result_extended`: name, args, kwargs, retries, queue) | No | Sí | Opt-in `RESULT_EXTENDED`; `worker` = nombre de la función | S | 1 |
| 4 | API de tarea: `bind=True`, `self.request`, `self.update_state()`, estados propios (`PROGRESS`) | No (solo `f(args, kwargs)`) | Sí | Decorador `@celery_cloud.task` + `TaskContext`; convive con el contrato actual | M | 2 |
| 5 | Excepciones de control `Ignore`, `Reject`, `Retry` | No | Sí | `Ignore` = no escribir estado; `Reject(requeue=True)` = `batchItemFailures`; `Retry` ver 6 | S | 2 |
| 6 | Reintentos: `self.retry`, `autoretry_for`, `max_retries`, `default_retry_delay`, `retry_backoff`, `retry_jitter`, estado `RETRY` | No (un fallo es definitivo) | Sí | Reenviar el mensaje con `retries+1` y retraso (ver 7); la protección de duplicados distingue reintento de duplicado | L | 2-3 |
| 7 | `eta` / `countdown` | Ignorados | Parcial | Retraso con SQS `DelaySeconds` (máx. 15 min) y **saltos** de 15 min hasta llegar a la hora; sin límite de fecha | M | 3 |
| 8 | Tareas periódicas (`celery beat`) | No | Parcial | Lambda planificadora + EventBridge Scheduler; no hay equivalente exacto de todos los `crontab` (sin solar, sin `nowfun`) | M | 3 |
| 9 | Callbacks: `link`, `link_error` | No | Sí | Leer `embed.callbacks/errbacks` y enviar los mensajes siguientes al terminar | M | 4 |
| 10 | `chain` | No | Sí | Leer `embed.chain` y enviar el siguiente paso con el resultado como primer argumento | M | 4 |
| 11 | `chord` (y `group` con callback, `map`/`starmap`/`chunks`) | No | Parcial | Contador atómico en DynamoDB (el backend de Celery ya lo prevé: atributo `chord_count`) y envío del cuerpo con la lista de resultados; `map`/`starmap`/`chunks` son tareas internas de Celery y requieren reimplementarlas | L | 4 |
| 12 | `revoke` (antes de ejecutarse) | Sin efecto | Parcial | Ayuda **opcional** de cliente que escribe `REVOKED` en DynamoDB; el runner lo respeta al registrar la tarea | M | 5 |
| 13 | `revoke(terminate=True)` de una tarea en ejecución | Sin efecto | Parcial | Solo cooperativo: la tarea consulta `self.is_revoked()`; no se puede matar un hilo de forma segura | S | 5 |
| 14 | Concurrencia dentro de un worker (`-c`) | Lote secuencial | Sí | `BATCH_CONCURRENCY` con hilos (incompatible con 2 mientras no se aísle por proceso) | M | 5 |
| 15 | `rate_limit` | No | Parcial | AWS ya limita por `MaximumConcurrency` y reserved concurrency (documentar); limitador por token bucket en DynamoDB solo si hay demanda | M | 5 |
| 16 | Serializadores `msgpack`, `yaml` y compresión (`gzip`, `zlib`, `bzip2`) | Solo `json` sin compresión | Sí | Extras opcionales por tipo de contenido y `content-encoding`/`compression` | M | 5 |
| 17 | Señales (`task_prerun`, `task_postrun`, `task_failure`...) y `on_success`/`on_failure` | No | Sí | Registro simple de *hooks* en el decorador y a nivel de módulo | S | 5 |
| 18 | Monitorización (eventos, Flower) | No | Parcial | Métricas CloudWatch (EMF) y logs JSON; **no** eventos de Celery (ver 4) | M | 5 |
| 19 | Varias colas, rutas, prioridades | Una cola por *event source mapping* | Sí | Sin código: un mapping por cola (misma función o una por cola) y prioridades = colas distintas; documentar | S | 5 (docs) |
| 20 | `task_always_eager`, `apply()` | Funciona (lado cliente) | Sí | Nada que hacer | – | – |

## 4. Qué no se hará (o no conviene) y por qué

| Característica | Motivo |
| --- | --- |
| Serializador `pickle` | Ejecutar `pickle` de un mensaje de cola es ejecución remota de código. Se rechaza a propósito. |
| Pools `prefork`/`eventlet`/`gevent`, `autoscale`, `prefetch`, `max_tasks_per_child` | No hay proceso worker: AWS escala las invocaciones y recicla los entornos. |
| `celery inspect`/`control` (ping, active, stats, `rate_limit` remoto, `add_consumer`...) | Usan difusión (pidbox) a workers vivos; no hay workers a quienes preguntar. |
| Eventos de Celery y Flower | Dependen de los eventos de worker difundidos por el broker. Sustituto: métricas y logs (fila 18). |
| Resultados > 400 KB en DynamoDB, de forma transparente | El cliente de Celery lee solo DynamoDB: un desvío a S3 exige un backend propio también en el cliente. Hoy el resultado grande se convierte en `FAILURE` claro (decisión 2 de la ronda 2). |
| Colas FIFO | El transporte SQS de Celery/kombu usa colas estándar. |
| Mensajes firmados (`auth` serializer) | La autenticación equivalente es IAM sobre `sqs:SendMessage`. |
| Prioridad dentro de una cola | SQS no la tiene (fila 19: una cola por prioridad). |
| Tareas de más de 15 min | Límite de Lambda (documentado). Alternativas: dividir o Step Functions/Fargate. |

## 5. Plan por fases

Cada tarea termina con: tests unitarios, test de integración con `moto`, **prueba con cliente Celery real** (nuevo script en `documentation/evidence/e2e/`), actualización de README y `pages_source/`, y revisión de mutación de los módulos nuevos.

### Fase 1: fidelidad y fiabilidad (sin API nueva, el cliente no cambia)

**P1.1 Excepción original.** `_failure_payload` pasa a usar la excepción original (`error.__cause__` cuando es `TaskExecutionException`): `exc_type=type(orig).__name__`, `exc_module=type(orig).__module__`, `exc_message=list(orig.args)` (serializable, con `str()` como respaldo). Para errores devueltos por una Lambda remota se usa `errorType`/`errorMessage` de su payload. Consecuencia: el cliente puede hacer `except ValueError`; para excepciones propias que el cliente no pueda importar, Celery crea una clase con ese nombre. **Cambio de comportamiento** (hoy siempre `TaskExecutionException`): documentarlo y subir versión menor. Verificación: cliente real, `pytest.raises(ValueError)`.

**P1.2 Plazos de Lambda.** Pasar `context` al handler (hoy se ignora). Calcular el tiempo restante; con `SIGALRM` en el hilo principal lanzar `SoftTimeLimitExceeded` (excepción propia con `exc_module="celery.exceptions"` para que el cliente la reconozca) y registrar `FAILURE` antes de que AWS mate la función (margen `TIMEOUT_MARGIN_SECONDS`, por defecto 10 s). Respetar los `time_limit`/`soft_time_limit` del mensaje (`headers.timelimit = [hard, soft]`) si son menores. Los registros del lote que no hayan empezado cuando falte tiempo se devuelven en `batchItemFailures` en vez de arrancarlos. Esto resuelve el caso "tarea atascada en `STARTED` por timeout" (no el de caída por falta de memoria). Riesgo: `SIGALRM` interrumpe código Python y llamadas bloqueantes interrumpibles, no extensiones C que no devuelvan el control; por eso sigue existiendo el timeout de Lambda como red de seguridad. Verificación: tarea que duerme más que el plazo, con el contexto simulado.

**P1.3 Metadatos.** `worker` (nombre de la función) en el resultado y `RESULT_EXTENDED=true` (opt-in, porque guarda argumentos y pueden ser sensibles). Test de que el cliente (`result_extended=True`) los lee.

**P1.4 Pruebas que faltan**: test automático de `group` (hoy solo medido a mano).

Esfuerzo de la fase: ~3-4 días.

### Fase 2: API de tarea compatible con Celery

**P2.1 `@celery_cloud.task`.** Módulo nuevo `celery_cloud/tasks.py`. El decorador marca la función con sus opciones (`name`, `bind`, `max_retries`, `default_retry_delay`, `autoretry_for`, `retry_backoff`, `retry_jitter`, `soft_time_limit`, `time_limit`, `ignore_result`). La estrategia local detecta el marcador y llama con **argumentos naturales**: `add(x, y)` en vez de `add(args, kwargs)`. Las funciones sin decorar siguen usando el contrato actual.

```python
from celery_cloud import task

@task(bind=True, max_retries=3, default_retry_delay=30)
def fetch(self, url: str) -> str:
    try:
        return download(url)
    except ConnectionError as exc:
        raise self.retry(exc=exc)
```

**P2.2 `TaskContext`.** `self.request` (`id`, `retries`, `args`, `kwargs`, `eta`, `expires`, `parent_id`, `root_id`, `group`, `headers`), `self.update_state(state, meta)` (escribe en el backend un estado propio, p. ej. `PROGRESS`, que el cliente lee con `result.state`/`result.info`), `self.retry(...)`, `self.is_revoked()` (Fase 5).

**P2.3 Excepciones de control.** `Ignore` (no se escribe resultado), `Reject(requeue=True)` (el mensaje se devuelve en `batchItemFailures`), `Retry` (interna, la lanza `self.retry`).

Esfuerzo: ~4-5 días sin reintentos; los reintentos (P3.2) comparten mecanismo con `eta`.

### Fase 3: tiempo (eta, reintentos, periódicas)

**P3.1 `eta`/`countdown`.** Si la hora `eta` del mensaje es futura, el runner **no registra ni ejecuta** la tarea: reenvía el mismo mensaje a la misma cola con `DelaySeconds=min(restante, 900)` y borra el original (devuelve éxito para ese registro). Cada salto es un mensaje nuevo, de modo que `maxReceiveCount` y la retención de la cola no se agotan. Si el reenvío falla, el registro se devuelve en `batchItemFailures` (el original no se pierde). La cola se deduce de `eventSourceARN` del propio registro (sin configuración nueva); hace falta `sqs:SendMessage` en el rol del runner. Límites: precisión de segundos más la latencia de SQS; una tarea con `eta` a días vista genera un mensaje cada 15 min (coste despreciable, pero documentarlo). Alternativa para plazos largos y exactos: EventBridge Scheduler de un solo disparo (solo documentación).

**P3.2 Reintentos.** `self.retry(countdown=...)`/`autoretry_for`: el runner reescribe la cabecera del mismo mensaje (`retries+1`, `eta=ahora+countdown`) y lo envía con el mecanismo de P3.1; el estado pasa a `RETRY` con la excepción. Punto delicado: el **registro condicional** actual (`attribute_not_exists(id)`) descartaría el reintento como duplicado, porque tiene el mismo `task_id`. Diseño: guardar un atributo numérico `retries` visible solo para el runner y aceptar el mensaje si no existe, o si `estado == RETRY` y `retries_del_mensaje > retries_guardado` (condición atómica). Un duplicado del propio mensaje de reintento queda bloqueado (mismo `retries`). `max_retries` agotado → `FAILURE` con la última excepción. `retry_backoff`/`retry_jitter` se calculan en el runner con la fórmula de Celery.

**P3.3 Tareas periódicas.** Un handler nuevo `celery_cloud.runners.scheduler.lambda_handler` que recibe `{"task": "nombre", "args": [], "kwargs": {}}` (lo invoca EventBridge Scheduler con una expresión `cron`/`rate`) y **construye y envía el mensaje Celery** a la cola con un `task_id` nuevo en cada ejecución. Es necesario porque un mensaje estático reutilizaría el `task_id` y el runner lo descartaría como duplicado. Incluye el constructor de mensajes (`celery_cloud/messaging.py`, protocolo 2, validado con kombu/Celery real), que también usan las fases 4 y 5. Documentación: tabla `crontab` de Celery ⇄ `cron` de EventBridge y las diferencias (zona horaria explícita, sin solar). Alternativa a evaluar en el spike: las variables de contexto de EventBridge Scheduler (`<aws.scheduler.execution-id>`) como id único sin Lambda planificadora **(por verificar)**.

Esfuerzo de la fase: ~7-9 días.

### Fase 4: canvas (callbacks, chain, chord)

Requiere que el runner **envíe mensajes nuevos** desde una firma (`messaging.build_message(signature, args_prefix, parent_id, root_id, group...)`).

**P4.1 `link` y `link_error`.** Leer `embed.callbacks` y `embed.errbacks`; al terminar con éxito, para cada callback enviar la tarea con `(resultado, *args_de_la_firma)` (o solo sus args si la firma es `immutable`), con `parent_id`/`root_id`. Para errbacks: Celery decide por la firma de la tarea del cliente si el errback recibe `(request, exc, traceback)` o solo el `uuid`; el runner no conoce esa firma. Decisión por defecto: estilo antiguo (`uuid`), documentado; hay que verificarlo con un cliente real (riesgo: **medio**).

**P4.2 `chain`.** Leer `embed.chain` (la lista de pasos restantes, el siguiente al final) y enviar el siguiente paso con el resultado como primer argumento y `chain` con el resto. Si un paso falla, la cadena se detiene y se llaman los errbacks.

**P4.3 `chord`.** Lo más delicado. Para cada tarea de la cabecera (`embed.chord` y `group` presentes), tras guardar su resultado, incrementar de forma atómica el contador del grupo en DynamoDB (el backend de Celery ya define `chord_count` y escribe el elemento inicial al crear el chord, comprobado en su código fuente) y, cuando el contador alcance el tamaño del grupo, leer los resultados de la cabecera y enviar el cuerpo con la lista. Errores de la cabecera: `ChordError` y errbacks del cuerpo. `map`/`starmap`/`chunks` y `celery.chord_unlock` son tareas internas de Celery: `map`/`starmap` se expanden en el cliente solo en parte, así que hay que probarlas una a una y, si no encajan, quedan como limitación. **Primer paso: un spike** que lea con exactitud `DynamoDBBackend` y `Backend.on_chord_part_return` de la versión fijada de Celery y que defina qué claves lee/escribe; la implementación copia ese protocolo y se verifica con `chord` real de cliente.

Esfuerzo de la fase: ~8-12 días (el chord es la mitad). Si el spike mostrara que replicar el backend es frágil, ver D2 (usar Celery como extra opcional dentro del runner para el canvas).

### Fase 5: operación y extras (independientes entre sí, por demanda)

- **P5.1 `revoke`** (opcional, requiere código de cliente): función `celery_cloud.client.revoke(task_id)` o `install(app)`, que sustituye `app.control.revoke` por una escritura de `REVOKED` en DynamoDB (condicional: si la tarea aún no empezó). El runner respeta un `REVOKED` previo al registrar (hoy lo vería como duplicado). `terminate=True` solo cooperativo (`self.is_revoked()`), documentado.
- **P5.2 Concurrencia en el lote** (`BATCH_CONCURRENCY`): hilos con el resultado por registro ya aislado. Incompatible con `SIGALRM` (solo hilo principal): con concurrencia > 1 el plazo se vigila por margen, no por señal; documentarlo.
- **P5.3 Serializadores y compresión**: `msgpack` y `yaml` como extras (`pip install celery-cloud[msgpack]`) y `gzip`/`zlib`/`bzip2`.
- **P5.4 Hooks/señales** y **P5.5 métricas EMF** (`TaskSucceeded`, `TaskFailed`, `TaskDuration`, `Skipped`, `Retried`).
- **P5.6 `rate_limit`**: documentar los límites de AWS; limitador propio solo si se pide.
- **P5.7 Colas/rutas/prioridades**: documentación con ejemplos de varios *event source mappings* y de una función por cola.

## 6. Orden, dependencias y esfuerzo total

```text
Fase 1 ──► Fase 2 ──► Fase 3 (P3.1 antes de P3.2; messaging antes de P3.3) ──► Fase 4 (usa messaging de P3.3)
                                  └──────────────────────────────────────────► Fase 5 (cada tarea por separado)
```

| Fase | Esfuerzo | Valor |
| --- | --- | --- |
| 1 Fidelidad y fiabilidad | 3-4 días | Alto: arregla tareas atascadas por timeout y tipos de excepción |
| 2 API de tarea | 4-5 días | Alto: abre `bind`, `update_state`, `retry` |
| 3 Tiempo | 7-9 días | Alto: `eta`, reintentos y periódicas son lo más pedido |
| 4 Canvas | 8-12 días | Medio-alto: sin `chain`/`chord` muchos flujos de Celery no migran |
| 5 Extras | 1-2 días cada uno | Según demanda |

Total orientativo para fases 1-4: **22-30 días de trabajo**. Cada fase deja el proyecto en estado publicable, de modo que se puede parar tras cualquiera.

## 7. Decisiones

### Decisiones tomadas por el propietario (2026-11-17)

| # | Decisión |
| --- | --- |
| D1 | Se ejecutan **todas las fases** (1 a 5). |
| D2 | **Código propio, sin Celery en el runner** (opción A). |
| D3 | El cliente recibe la **excepción original**. **La versión se mantiene en 0.2.0** (no se sube a 0.3.0). |
| D4 | El decorador nuevo **convive** con el contrato `f(args, kwargs)`. |
| D5 | `link_error` en estilo antiguo (recibe el `uuid`). |
| D6 | Tareas periódicas: **solo documentación de EventBridge**, sin desarrollo propio (se elimina P3.3 como código; queda como guía). |
| D7 | Ayuda opcional de cliente para `revoke`: de acuerdo. |
| D8 | Concurrencia en el lote 1 por defecto. |
| S3 | **Resultados > 400 KB: se mantienen como `FAILURE` claro. El almacenamiento en S3 queda aplazado** (se valoró; exige además un backend propio en el cliente, porque el cliente Celery estándar solo lee DynamoDB). |

### Propuesta original (histórica)

Se plantearon una a una, con recomendación, antes de empezar cada fase.

- **D1. Alcance.** ¿Hasta qué fase? Recomendación: **1 y 2 ya**, decidir 3-4 después de ver cómo queda.
- **D2. ¿Enviar mensajes con código propio o con Celery dentro del runner?** (afecta a las fases 3-4). Opción A: constructor de mensajes propio (`messaging.py`), runner sin Celery, más código y riesgo de incompatibilidad en el protocolo. Opción B: `pip install celery-cloud[canvas]` añade Celery al runner y delega en él (`signature().apply_async`, `backend.on_chord_part_return`): menos código y compatibilidad exacta, a cambio de imagen más grande (decenas de MB), arranque en frío más lento y configurar broker/backend en el runner. Recomendación: **A**, con el spike del chord como criterio; B solo si el chord resulta frágil.
- **D3. Cambio de comportamiento de P1.1** (tipo de excepción original en lugar de `TaskExecutionException`). Recomendación: **sí**, con versión menor (0.3.0).
- **D4. API de tarea nueva** (`@celery_cloud.task`) **conviviendo** con el contrato `f(args, kwargs)`. Recomendación: **convivir**, sin retirar el antiguo.
- **D5. Errbacks de `link_error`:** estilo antiguo (`uuid`) por defecto. Recomendación: sí, documentado, y verificar con cliente real.
- **D6. Periódicas:** Lambda planificadora propia (recomendado, probada de extremo a extremo con moto) frente a solo documentación de EventBridge.
- **D7. `revoke`:** ¿aceptas una ayuda **opcional** de cliente (el cliente deja de ser "solo Celery estándar" para esa función)? Recomendación: sí, opcional, y mantener `revoke` estándar documentado como sin efecto.
- **D8. Concurrencia en el lote vs. límites de tiempo con señal:** mutuamente excluyentes en la primera versión. Recomendación: concurrencia 1 por defecto.

## 8. Riesgos transversales

- **Protocolo de mensajes de Celery:** cambia entre versiones mayores. Mitigación: fijar versiones probadas en un test de interoperabilidad con el Celery real (ya existe el procedimiento) y ejecutarlo en CI de forma opcional.
- **Duplicados y reintentos:** la escritura condicional es lo que protege de dobles ejecuciones; las fases 2-4 la tocan. Mitigación: tests de mutación centrados en esas condiciones (en esta auditoría, quitarla hizo fallar un test).
- **Permisos nuevos del rol del runner** (`sqs:SendMessage`, y `dynamodb:UpdateItem` ya existente): actualizar `iam-roles.rst`.
- **Coste:** `eta` y reintentos generan mensajes extra de SQS; despreciable, pero se documenta.
