# Pendientes (anotados el 2026-11-17)

Estado de partida: todo el trabajo está **sin commitear** en el árbol de trabajo (75 entradas en `git status`). 545 tests, `ruff`/`mypy`/`bandit` limpios, cobertura 99 %, mutación 92,5 %, documentación Sphinx generada en `docs/`. Detalle en `03`, `05`, `07`.

## 1. Commits y publicación (lo primero)

- [ ] **Decidir cómo trocear los commits.** Propuesta: (1) licencia MPL-2.0 y versión 0.2.0; (2) auditoría de calidad (`documentation/`, correcciones, tests); (3) README + TTL; (4) paridad con Celery (fases 1-5); (5) documentación Sphinx y workflows.
- [ ] **Activar GitHub Pages** (rama `main`, carpeta `/docs`). El README apunta a `https://impalah.github.io/celery-cloud/`; confirmar la URL.
- [ ] **`release.yml`:** el bump automático está comentado, así que cada push a `main` intenta publicar la misma versión en PyPI y **falla** hasta subir la versión a mano. Decidir: dejar solo `release`/`workflow_dispatch` como disparadores, o comprobar antes si la versión ya existe en PyPI (como hace `auth-middleware`).
- [ ] **Primer release 0.2.0:** subir a PyPI y publicar una **imagen nueva en ECR** (las publicadas llegan a `0.1.25` y no tienen ninguna corrección). Valorar incluir los extras `msgpack`/`yaml` en la imagen.
- [ ] **Ningún workflow se ha ejecutado** (`ci.yml`, `docs.yml`, `release.yml`, `mutation.yml`, Dependabot): solo se validó su YAML. Vigilar la primera ejecución, sobre todo `docs.yml` (commitea `docs/` con `GITHUB_TOKEN`).

## 2. Verificación contra AWS real (nada se ha probado fuera de `moto`)

- [x] **Terraform (`infra/terraform/`)** aplicado en real el 2026-11-19 (ver `07`). `terraform destroy` de la pila `test` ejecutado el 2026-11-19 (17 recursos, limpio, sin restos en la cuenta). Para repetirlo: `tfvars` y `local_backend_override.tf` locales (git-ignorados) siguen en `stacks/example`; hay que reconstruir y subir la imagen.

- [ ] Los comandos de `aws` de `pages_source/infrastructure/` y del README (cola, tabla, ECR, función, *event source mapping*).
- [ ] Permisos IAM nuevos: `sqs:SendMessage` (eta, reintentos, workflows) y `dynamodb:DeleteItem`.
- [ ] `DelaySeconds` real y el reenvío en saltos de 15 min.
- [ ] `SIGALRM` dentro del runtime de Python de Lambda (límites de tiempo y margen antes del timeout).
- [ ] Borrado real por TTL y la latencia de DynamoDB.
- [ ] `batchItemFailures` con `ReportBatchItemFailures` (reentrega real de SQS).
- [ ] Tareas `lambda://` contra una función real.
- [x] Módulo Terraform `schedules` y comandos manuales de `periodic-tasks.rst` probados en real (ver `07`). Pendiente: si EventBridge Scheduler puede aportar un id único por ejecución (hoy solo se documenta `ignore_result`).
- [ ] Renderizado de los diagramas Mermaid de la documentación publicada.

## 3. Funcionalidad sin probar o con limitaciones conocidas

- [ ] Workflows anidados: cadenas dentro de un chord, chord dentro de chord, grupos anidados.
- [ ] `link_error` de estilo nuevo (`(request, exc, traceback)`): solo se usa el estilo antiguo (`uuid`).
- [ ] Si SQS rechaza los mensajes siguientes de un workflow, el callback se pierde (solo log). Valorar un mecanismo de recuperación.
- [ ] Con `BATCH_CONCURRENCY` > 1 los límites de tiempo no interrumpen tareas (solo el margen antes de empezar cada registro).
- [ ] **Aplazado por decisión del propietario:** resultados > 400 KB en S3 (hoy `FAILURE`). Requiere un backend propio en el cliente, porque el cliente Celery estándar solo lee DynamoDB.
- [ ] No implementado (documentado): `rate_limit`, `celery inspect/control`, clases de tarea (`base=`), pickle, brotli/zstd, compresión de resultados, colas FIFO.

## 4. Calidad y mantenimiento

- [ ] Revisar con calma la documentación generada (`docs/`) leyendo las páginas nuevas: se comprobó que compila sin avisos y que los ejemplos funcionan, pero no se ha leído como lectura final.
- [ ] `pages_source/examples/server/env.json` solo lista las tareas de la calculadora y `remote.sum`; añadir las de `jobs.*` si se quiere un despliegue de ejemplo completo.
- [ ] CI con matriz de Python (3.12/3.13/3.14), como `auth-middleware` (hoy solo se prueba la versión de `pyproject.toml`).
- [ ] Mutación: 226 supervivientes aceptados (textos de log/error y equivalentes). Revisar si compensa fijar los `detail=` de las excepciones internas.
- [ ] Mantener los scripts de `documentation/evidence/e2e/` como prueba de interoperabilidad: valorar ejecutarlos de forma opcional en CI.
- [ ] `docs_source/` (con el `.drawio` de la arquitectura) quedó sin usar: decidir si se integra en la documentación o se elimina.
