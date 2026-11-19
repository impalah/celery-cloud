# Mutation testing

La cobertura mide qué líneas ejecutan los tests, no si los tests *detectan* un fallo. Mutation testing introduce cambios pequeños en el código (invertir una condición, cambiar una constante, vaciar un mensaje) y comprueba que algún test falla. Un mutante que sobrevive indica una aserción que falta.

## Cómo se usa

```bash
make mutation          # ejecuta mutmut (≈10 s)
make mutation-report   # lista los mutantes supervivientes
uv run mutmut show <nombre>   # diff de un mutante concreto
```

- **No forma parte del CI habitual** (`ci.yml`, `release.yml`) ni de `make check`. Existe un workflow manual, `.github/workflows/mutation.yml` (solo `workflow_dispatch`).
- Configuración en `[tool.mutmut]` de `pyproject.toml`. Solo se mutan los módulos críticos: `settings`, `sqs_entities`, `task`, `task_model`, `aws_lambda`, `lambda_strategy`, `local_strategy` y `task_executor`. Quedan fuera `debug_server.py` y `logging.py`.
- Cuándo ejecutarlo: al cambiar de forma importante esos módulos, o antes de una versión relevante.
- Los resultados se guardan en `mutants/` (ignorado por git).

## Resultado de la primera ronda (2026-11-17)

| | Mutantes | Detectados | Supervivientes | Puntuación |
| --- | --- | --- | --- | --- |
| Inicial (126 tests) | 799 | 564 | 235 | 70,6 % |
| Tras la primera ronda (183 tests) | 799 | 753 | 46 | 94,2 % |
| Tras el TTL de resultados (198 tests) | 826 | 780 | 46 | **94,4 %** |

El mutante nuevo que apareció con el código del TTL (`seconds <= 0` → `<= 1`) era real y se cerró con un test del límite. Los 57 tests de la primera ronda fijan lo que antes no se comprobaba: valores por defecto y nombre de cada variable de entorno, `message` y `detail` exactos de cada excepción (se devuelven al cliente), formato completo del estado guardado (`date_done`, `traceback`, `children`, `timestamp`), el límite inclusivo de 380 000 bytes, los parámetros del circuit breaker, que un registro duplicado o caducado no detenga el resto del lote y que el `task_id` sea `None` cuando el fallo ocurre antes de decodificar la tarea.

## Supervivientes aceptados (46)

| Tipo | Nº | Por qué se aceptan |
| --- | --- | --- |
| Mensajes de log (`logger.debug(None)`, texto en mayúsculas…) | 38 | Los logs no son parte del contrato; comprobarlos exige acoplar los tests a su texto. |
| Valores por defecto explícitos que se quitan (`result=None`, `traceback=None`, `children=[]`) | 4 | **Equivalentes**: `TaskResult` ya tiene esos mismos defaults. |
| `traceback.format_exception(None, error, tb)` y `type(None)` | 2 | **Equivalentes**: desde Python 3.10 el primer argumento se ignora si se pasa la excepción. |
| `decode("UTF-8")` en vez de `"utf-8"` | 2 | **Equivalentes**: Python normaliza el nombre del códec. |

Si una ejecución futura muestra supervivientes fuera de esta tabla, son candidatos a un test nuevo.

## Qué enseñó esta ronda

- La mayoría de supervivientes eran mensajes de error sin comprobar y valores por defecto. Es el tipo de hueco que los tests con mocks dejan pasar y que la cobertura de líneas no ve.
- Dos aserciones que parecían suficientes (`assert exc.value.detail`) aceptaban el texto `"None"` e incluso `detail=None`; se endurecieron.
- Un mutante señaló un caso real: tras un duplicado o una tarea caducada, el resto del lote debe seguir procesándose. Ahora hay un test que lo garantiza.

## Ronda de paridad con Celery (2026-11-17)

Tras `06`/`07` el conjunto mutado pasa de 8 a 16 módulos (se añaden `tasks`, `messaging`, `deadline`, `serialization`, `client`, `runners/canvas`, `runners/builtin_tasks` y `models/canvas_model`).

| | Mutantes | Detectados | Supervivientes |
| --- | --- | --- | --- |
| Primera pasada | 3021 | 2625 (86,9 %) | 396 |
| Tras tests dirigidos | 3021 | **2795 (92,5 %)** | **226** |

Los tests dirigidos fijan lo que de verdad importaba (`tests/integration/test_mutation_gaps.py` y los añadidos a `test_messaging.py`, `test_client.py` y `test_local_strategy.py`): el **protocolo del mensaje** campo a campo (un test "dorado" con las cabeceras y propiedades que escribe kombu), todos los campos de `self.request`, el metadato extendido en cada estado, los argumentos de cada señal, los límites de los plazos (justo en el margen, `eta` a un segundo) y los elementos de BD (reescritura completa en la toma de control, lecturas consistentes, limpieza del contador del chord).

**Supervivientes aceptados (226):** unos 74 son textos de log o de errores internos (`detail=`), y el resto son equivalentes o ruido: marcas de tiempo (`datetime.now(None)`), valores por defecto redundantes (`result=None`, `children=[]` ya son el valor por defecto del modelo), `strict=` de `zip`, `range(10)` frente a `range(11)` en el desenvuelto de excepciones y opciones de `msgpack` (`use_bin_type`) sin efecto observable en el viaje de ida y vuelta.
