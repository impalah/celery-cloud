# Verificación del README

Fecha: 2026-11-17. Objetivo: comprobar que el README (explicación, instalación, despliegue y ejemplos) es correcto y lleva a un resultado útil. Esta verificación sustituye la limitación que figuraba en `03-registro-remediacion.md` ("no se pudo probar la interoperabilidad con Celery real").

## Qué se probó y cómo

El flujo completo se ejecutó con un **cliente Celery 5.7.0 real** (`celery[sqs,dynamodb]`, kombu 5.7.0) contra **SQS y DynamoDB simulados con `moto`** (5.2.5), y el runner de este repositorio. No se usó ninguna cuenta de AWS.

| # | Prueba | Resultado |
| --- | --- | --- |
| A | El cliente del README envía `add(10, 3)`; el handler procesa el mensaje real que produjo Celery; el cliente lee el resultado | `SUCCESS`, `result.get()` = **13** |
| B | Una tarea que lanza excepción | El cliente ve `FAILURE`; `get()` lanza una excepción `TaskExecutionException` con el mensaje original; el traceback queda en `result.traceback` |
| C | Reentrega del mismo mensaje | `skipped_messages: 1`, la tarea no se vuelve a ejecutar |
| D | Contenido de la tabla | Las filas del runner tenían `id`, `result` y `timestamp`, **sin `ttl`** (corregido, ver más abajo: ahora llevan `ttl`) |
| E | Imagen del `Dockerfile` ampliada con `COPY my_tasks.py ${LAMBDA_TASK_ROOT}/`, ejecutada con el emulador de Lambda (RIE) | El handler responde `completed` y el cliente lee **42** (`20 + 22`) |
| F | `pip install celery-cloud` en un entorno limpio | Instala y se importa; **no instala Celery** |
| G | Cada bloque de código y JSON del README | Compilan/validan; el cliente del README es byte a byte el ejecutado; los JSON de `TASKS` los acepta `Settings`; todos los ajustes documentados existen; los enlaces internos resuelven |

Esto confirma además que la clave `b'celery-task-meta-<id>'` y el formato de `FAILURE` son compatibles con el backend de Celery.

## Errores encontrados en el README anterior

| Problema | Evidencia | Corrección |
| --- | --- | --- |
| El ejemplo de cliente **no era Python válido** (`CELERY_BROKER_SQS_QUEUE_URL=https://...` sin comillas) | `SyntaxError` al compilar el bloque | Cliente nuevo, completo y ejecutado de extremo a extremo |
| El nombre de la tarea del ejemplo no coincidía con ningún `TASKS` del README | Celery nombra `client.add` o `task_client.add` según cómo se importe | `@app.task(name="tasks.add")` explícito y mismo nombre en `TASKS` |
| `broker_transport_options["dead_letter_queue"]` | No existe en kombu 5.7 (`grep` sin resultados): se ignoraba en silencio | Eliminada |
| `task.revoke(terminate=True)` para "cancelar" | Acepta la llamada pero el runner no implementa control remoto: no cancela nada | Sustituido por `result.get(timeout=...)`; documentado como no soportado |
| Opciones `worker_*` en la configuración del cliente | Son de worker, el cliente no las usa | Eliminadas |
| Frase "The image can be downloaded from:" sin URL; sin proceso de despliegue | — | URI y galería de la imagen y despliegue completo paso a paso |
| El diagrama decía "SWS Dispatcher" | Errata | "event source mapping" |
| "Using the provided container directly in a Function" | La documentación de AWS exige que la imagen esté en un repositorio de **Amazon ECR de la misma región** que la función | Pasos para copiar la imagen a ECR propio |
| No decía que `pip install celery-cloud` no instala Celery | Prueba F | Tabla "qué instalar dónde" |
| Sin permisos IAM | — | Tabla de permisos del runner y del cliente |
| Imagen publicada | Tags existentes: `0.1.5`, `0.1.10`, `0.1.18`, `0.1.25`; no hay `latest` ni `0.1.29` | Se documenta que no hay `latest` y que los tags pueden ir por detrás de PyPI |

## Hallazgos nuevos

1. **El runner no escribía el campo `ttl`** (corregido, ver la sección siguiente).
2. **Las imágenes publicadas son anteriores a las correcciones de esta auditoría** (la última es `0.1.25`). Quien despliegue la imagen pública tiene el comportamiento antiguo (los bugs C1–C5) hasta que se publique una versión nueva. El README describe el comportamiento del código actual.

## TTL de los resultados (implementado)

**Corrección de un error mío.** Al proponer esta tarea afirmé que el cliente de Celery activa el TTL por defecto con 86 400 s y que ese era "el valor por defecto de Celery". Es falso: en el backend DynamoDB de Celery `time_to_live_seconds` vale `None` y solo se usa TTL si la URL del backend lleva `?ttl_seconds=N`. Lo que sí era cierto es que el runner no escribía `ttl`, de modo que, aun con TTL activado en la tabla, sus resultados no caducaban. También era incorrecto decir que el cliente necesita `DescribeTimeToLive`/`UpdateTimeToLive` siempre: solo si se usa `ttl_seconds`. El README ya está corregido.

**Qué se hizo**

- Nuevo ajuste `RESULT_TTL_SECONDS` (por defecto 86 400; `0` desactiva; negativo o no entero ⇒ error al arrancar).
- `TaskModel` escribe el atributo `ttl` (número, segundos epoch, `ahora + RESULT_TTL_SECONDS`) al registrar la tarea y lo **renueva** en cada actualización de estado, igual que el backend de Celery.
- El valor por defecto es seguro porque el atributo es **inerte hasta que se activa el TTL en la tabla** (`aws dynamodb update-time-to-live ... AttributeName=ttl`, documentado en el README). Hasta entonces no se borra nada.

**Verificación (cliente Celery 5.7 real contra `moto`)**

- Un ítem escrito por el propio backend de Celery y uno escrito por el runner tienen **los mismos atributos y tipos** (`id: S`, `result: B`, `timestamp: N`, `ttl: N`) y el mismo significado del `ttl` (`ahora + N`): `ttl_compat.py`.
- Con el TTL activado en la tabla, el flujo A–C sigue funcionando.
- Un cliente configurado con `?ttl_seconds=3600` sigue leyendo los resultados del runner.
- 15 tests nuevos (ajuste, cálculo con reloj fijo, inserción/actualización, desactivado, límite de 1 s e integración con DynamoDB simulada, incluidos tareas fallidas).

**Efecto a tener en cuenta:** cuando DynamoDB borra una fila, el runner deja de recordar ese `task_id`; un duplicado muy tardío de SQS volvería a ejecutarse. Documentado en el README (mantener `RESULT_TTL_SECONDS` mayor que la retención de la cola).

**No verificado:** el borrado real de ítems caducados (`moto` no lo simula) y la latencia con la que DynamoDB borra tras la caducidad.

## Qué no se pudo verificar

- **Los comandos de AWS CLI** (`create-queue`, `create-table`, ECR, `create-function`, `create-event-source-mapping`) no se ejecutaron contra una cuenta real. Los recursos equivalentes sí se crearon con boto3 contra `moto`, y la tabla usa el esquema que funcionó (clave hash `id` de tipo cadena).
- **Lambda real, IAM real y SQS real.** Los permisos IAM de la tabla se han deducido del código del runner y del código fuente del backend de Celery, no probado contra IAM.
- **Tareas `lambda://`** contra una función real: solo cubiertas por tests unitarios (`moto` necesita Docker para ejecutar Lambdas).
- **El diagrama Mermaid** no se renderizó; es sintaxis estándar de GitHub.
- **Imagen en una función real:** se ejecutó con el emulador (RIE), no en AWS.
- La documentación de AWS consultada dice que la imagen debe estar *en un repositorio de Amazon ECR* de la misma región. **No** afirma que una imagen de un registro público no pueda usarse, y no menciona *pull-through cache*; el README lo expresa con esa cautela.

## Cómo repetir la prueba

Los scripts están en `documentation/evidence/e2e/`.

```bash
python3 -m venv /tmp/e2e && /tmp/e2e/bin/pip install "celery[sqs,dynamodb]" "moto[server,sqs,dynamodb]" /ruta/al/repo
moto_server -p 5555 &                      # AWS simulado
cd documentation/evidence/e2e && . ./env.sh
/tmp/e2e/bin/python - <<'PY'              # recursos: cola y tabla
import boto3
q = boto3.client("sqs").create_queue(QueueName="lambda-runner-queue")["QueueUrl"]
boto3.client("dynamodb").create_table(TableName="lambda-runner-tasks",
    KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
    AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}], BillingMode="PAY_PER_REQUEST")
open("queue_url.txt", "w").write(q)
PY
/tmp/e2e/bin/python driver.py              # pruebas A-D con el cliente del README
/tmp/e2e/bin/python ttl_compat.py client_ttl.py   # compara un ítem de Celery con uno del runner
```

`driver_rie.py` repite la prueba contra la imagen en un contenedor (`docker run -p 9000:8080`); para ello `moto_server` debe escuchar en la IP del puente de Docker (`-H 172.17.0.1`) y `AWS_ENDPOINT_URL` apuntar a ella.
