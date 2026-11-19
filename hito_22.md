# Hito 22 — Cola de tareas asíncronas con Redis y Celery

Este documento explica el ticket **#DEV-55**. La operación más pesada de la API (lanzar el pipeline
semanal de desempeño de negocio) ya no se ejecuta en el proceso de FastAPI. El endpoint la **encola**
en Redis y responde al instante `202 Accepted` con un `task_id`. Un **worker de Celery**,
en otro proceso y otro contenedor, la ejecuta, y el cliente consulta su estado cuando quiera
en `GET /tasks/{task_id}`. Si la tarea falla tres reintentos seguidos, queda registrada en una
**Dead Letter Queue** en la base de datos.

Está pensado para que alguien que no estuvo en el hito entienda qué se hizo, por qué se hizo así
y cómo se comprobó.

Entregables:

- [services/celery_app.py](services/celery_app.py): la instancia de Celery (Redis como broker y
  como backend de resultados, `REDIS_URL`).
- [services/tasks/](services/tasks/__init__.py): la clase base de las tareas (reintentos, logs y
  DLQ), la DLQ, el registro de tareas, la tarea del pipeline y `GET /tasks/{task_id}`.
- [services/tasks/sql/001_task_dead_letters.sql](services/tasks/sql/001_task_dead_letters.sql):
  la migración de la tabla `task_dead_letters`.
- `POST /reporting/pipeline-runs` ([services/reporting/router.py](services/reporting/router.py)):
  ahora encola y responde `202` con `task_id`.
- [docker-compose.yml](docker-compose.yml): servicios `redis`, `worker` y `flower`.
- [README.md](README.md#cola-de-tareas-worker-de-celery-y-flower-hito-22): cómo levantar y
  detener el worker.
- [tests/tasks/](tests/tasks/conftest.py): 39 tests nuevos, con un worker de Celery real. Los tests
  de `POST /reporting/pipeline-runs` se reescribieron para el modo Celery.

Rama: `feature/async-task-queue`. Sale de `feature/nightly-telemetry-export` (hito 21), porque el
PR del hito 21 aún no estaba fusionado cuando empezó este hito. Los hitos 17 a 20 ya están en
`main`.

| Commit | Fase |
|---|---|
| `16bf65f` | Fase 1 — Redis en Docker y dependencias (`celery`, `redis`, `flower`) |
| `6221ceb` | Fase 2 — Instancia de Celery, `TrackedTask` (reintentos, logs) y la DLQ |
| `0b420db` | Fase 3 — La tarea del pipeline y `POST /reporting/pipeline-runs` → `202` + `task_id` |
| `f817e3e` | Corrección — la DLQ se escribe antes de que Celery publique `FAILURE` |
| `e010b51` | Fase 4 — `GET /tasks/{task_id}` |
| `e522843` | Corrección — la DLQ, segura con varios procesos del worker |
| `855ab78` | Rendimiento — el primer `202` tras arrancar baja de 380 ms a 34 ms |
| `3ed42e0` | Fase 5 — Servicios `worker` y `flower` en Docker |
| `484b598` | Documentación — el worker en el README |
| (este documento) | Documentación — hito 22 |

---

## Índice

1. [El encargo](#1-el-encargo)
2. [Conceptos básicos](#2-conceptos-básicos)
3. [Arquitectura: quién hace qué](#3-arquitectura-quién-hace-qué)
4. [Fase 1 — Redis](#4-fase-1--redis)
5. [Fase 2 — Celery, `TrackedTask` y la Dead Letter Queue](#5-fase-2--celery-trackedtask-y-la-dead-letter-queue)
6. [Fase 3 — La operación pesada se convierte en tarea](#6-fase-3--la-operación-pesada-se-convierte-en-tarea)
7. [Fase 4 — `GET /tasks/{task_id}`](#7-fase-4--get-taskstask_id)
8. [Fase 5 — Worker y Flower en Docker](#8-fase-5--worker-y-flower-en-docker)
9. [Cuándo hice commit y por qué](#9-cuándo-hice-commit-y-por-qué)
10. [Problemas que aparecieron y cómo se resolvieron](#10-problemas-que-aparecieron-y-cómo-se-resolvieron)
11. [Cómo se comprobó](#11-cómo-se-comprobó)
12. [Cómo arrancarlo y probarlo](#12-cómo-arrancarlo-y-probarlo)
13. [Decisiones discutibles (y cómo defenderlas)](#13-decisiones-discutibles-y-cómo-defenderlas)
14. [Lo que queda pendiente](#14-lo-que-queda-pendiente)
15. [Cuerpo del PR](#15-cuerpo-del-pr)
16. [Archivos creados y modificados](#16-archivos-creados-y-modificados)
17. [Checklist de evaluación](#17-checklist-de-evaluación)
18. [Glosario](#18-glosario)

---

## 1. El encargo

El ticket pide desacoplar de la API las operaciones largas:

1. Redis corre en Docker como broker. La API y los workers usan el mismo.
2. La operación que más tarda en la API pasa a ser una tarea de Celery.
3. El endpoint responde `202 Accepted` con un `task_id` **sin esperar** (en menos de 200 ms).
4. `GET /tasks/{task_id}` devuelve el estado real (`pending`, `started`, `success`, `failure`) y
   el resultado cuando lo haya.
5. Reintentos automáticos (`max_retries=3`) con backoff exponencial. Si se agotan, la tarea
   pasa a una **Dead Letter Queue** registrada en la base de datos, con `task_id`, intento, error
   y timestamp.
6. Los workers son procesos separados de FastAPI.
7. Flower está levantado para ver la cola.
8. Cada tarea deja en el log su `task_id`, el intento, el estado resultante y la duración. Los
   fallos llevan además el error completo.

Y tres reglas del patrón productor/consumidor: **mensajes ligeros** (solo identificadores),
**ACK solo tras éxito** y **timeout en toda tarea**.

### Adaptación al repo

- **La operación elegida es `POST /reporting/pipeline-runs`.** Lanza el ETL semanal completo
  (extracción de `telemetry_events`, transformación con Pandas, carga en `reporting.*`). Con la base
  de la prueba tardó unos 20-25 s, y con un histórico real tardaría minutos. Ninguna otra operación
  de la API se le acerca. Según [CACHING_REPORT.md](CACHING_REPORT.md), lo siguiente más lento es
  `GET /inventory/orders`, con 2,1 s sin caché, y es una lectura: se arregla paginando, no
  encolando. `POST /analyze` procesa un CSV pequeño en milisegundos.
- **Ya respondía `202`, pero el trabajo seguía dentro de la API.** Hasta el hito 21, en el modo
  `local` (el de desarrollo), el flow corría en las `BackgroundTasks` de FastAPI: después de
  responder, sí, pero **dentro del proceso de Uvicorn**. Ese proceso compartía CPU y memoria
  (Pandas) con el resto de peticiones, y si la API se reiniciaba, la corrida se perdía. Ese es
  justo el problema que el ticket describe.
- **El trigger por Prefect (`deployment`) se mantiene.** Es la otra forma de lanzar la corrida, con
  un servidor de Prefect, y no la toca este hito.

---

## 2. Conceptos básicos

### Productor / consumidor

Quien **pide** el trabajo y quien lo **hace** son procesos distintos:

```
Cliente → API (productor) → Redis (broker) → worker (consumidor) → Redis (resultado)
```

La API solo publica un mensaje («ejecuta esta tarea con estos argumentos») y responde. El worker
escucha la cola, toma los mensajes de uno en uno y los ejecuta. Si el worker está caído, los
mensajes esperan en Redis.

### Broker y backend de resultados

- **Broker**: donde esperan los mensajes. Aquí es Redis, en la lista `celery`.
- **Backend de resultados**: donde el worker guarda el estado y el resultado de cada tarea
  (`celery-task-meta-<task_id>`). También es Redis. `GET /tasks/{task_id}` lee de ahí.

### ACK tardío (`acks_late`)

Un mensaje se da por procesado («ACK») cuando la tarea **termina**, no cuando el worker lo
recoge. Si el worker muere a mitad, el mensaje no se ha confirmado y vuelve a la cola.

### Backoff exponencial

Tras un fallo no se reintenta enseguida: se espera, y cada vez más (10 s, 20 s, 40 s). Si la causa
es pasajera (la base reiniciándose, la red), cada espera le da más margen para recuperarse.

### Dead Letter Queue (DLQ)

El sitio donde acaban las tareas que no se pudieron completar ni reintentando. Aquí es una tabla,
`task_dead_letters`. Cada fila dice qué tarea era, con qué argumentos, en qué intento murió y por
qué, para que alguien la investigue y, si procede, la relance.

---

## 3. Arquitectura: quién hace qué

```
                 POST /reporting/pipeline-runs                       GET /tasks/{task_id}
                              │                                              │
┌─────────────── backend (FastAPI) ───────────────┐                          │
│ 1. valida (lunes, rango, 409 si ya hay corrida) │                          │
│ 2. registry.register(task_id, dueño)  ──────────┼──► Redis                 │
│ 3. apply_async(kwargs={week_start, lookback,    │    ├─ lista `celery`  (mensajes)
│    triggered_by}, task_id)  ────────────────────┼──► ├─ trackflow-task-registry-<id>
│ 4. 202 {task_id}  +  Location: /tasks/<id>      │    └─ celery-task-meta-<id> ◄─────┘
└─────────────────────────────────────────────────┘          ▲          │
                                                             │          │ toma 1 mensaje
┌─────────────── worker (Celery, otro contenedor) ───────────┼──────────▼──────────────┐
│ TrackedTask.__call__: log started → run_weekly_performance_pipeline(...)             │
│   └─ data.pipelines.pipeline.weekly_warehouse_client_performance_flow (Prefect)      │
│        └─ escribe reporting.pipeline_runs y reporting.weekly_* (como siempre)        │
│ éxito  → SUCCESS + resultado en Redis, ACK, log success                              │
│ fallo  → RETRY con countdown 10/20/40 s (log retry) …                                │
│ 4º fallo → log ERROR + fila en task_dead_letters → FAILURE en Redis, ACK             │
└──────────────────────────────────────────────────────────────────────────────────────┘

flower (otro contenedor) ── escucha los eventos de Celery ──► http://localhost:5555
```

Quién escribe qué:

| Dato | Lo escribe | Dónde |
|---|---|---|
| El mensaje de la tarea | API (productor) | Redis, lista `celery` |
| Quién pidió la tarea y cuándo | API | Redis, `trackflow-task-registry-<id>` |
| Estado (`STARTED`, `RETRY`, `SUCCESS`, `FAILURE`) y resultado | Worker | Redis, `celery-task-meta-<id>` |
| La corrida del pipeline | El flow, dentro del worker | `reporting.pipeline_runs` (hito 19) |
| La tarea muerta | Worker | `task_dead_letters` (base de datos) |

---

## 4. Fase 1 — Redis

Servicio `redis` en [docker-compose.yml](docker-compose.yml):

```yaml
redis:
  image: redis:8.2-alpine          # imagen oficial
  command: ["redis-server", "--maxmemory-policy", "noeviction", "--appendonly", "yes"]
  ports: ["${REDIS_PORT:-6379}:6379"]
  volumes: [redis-data:/data]
  healthcheck: redis-cli ping
```

- **`noeviction`**: con la memoria llena, Redis **rechaza** escrituras nuevas en vez de borrar
  claves para hacer sitio. Con una política LRU podría tirar un mensaje encolado o el estado de una
  tarea en silencio. Es mejor que encolar falle con un 503 visible.
- **`appendonly yes`**: Redis escribe cada operación en disco. Los mensajes encolados sobreviven a
  un reinicio de Redis, no solo a uno del worker.
- **`REDIS_URL`** es la única variable de conexión. Desde el host vale `redis://localhost:6379/0`.
  Dentro de Docker, compose pone `redis://redis:6379/0` en el backend, el worker y Flower. Esa URL
  sale de `REDIS_URL_DOCKER`, para que la `REDIS_URL` del `.env`, que apunta al host, no se cuele en
  los contenedores.
- `uv add celery redis flower` (celery 5.7.0, redis 8.1.0, flower 2.2.0) y `services/requirements.txt`
  regenerado desde `uv.lock`, como en el resto del repo.

---

## 5. Fase 2 — Celery, `TrackedTask` y la Dead Letter Queue

### 5.1 La instancia de Celery

[services/celery_app.py](services/celery_app.py) crea `app = Celery("trackflow", broker=REDIS_URL,
backend=REDIS_URL)`. No importa FastAPI ni la configuración de la API: lo importan tanto la API
(para encolar) como el worker (para ejecutar).

Las tres reglas del patrón, en la configuración:

| Regla | Configuración |
|---|---|
| Mensajes ligeros | `task_serializer="json"`, `accept_content=["json"]` (nada de pickle) y argumentos que son solo identificadores (§6) |
| ACK solo tras éxito | `task_acks_late=True`, `task_reject_on_worker_lost=True`, `worker_prefetch_multiplier=1` |
| Timeout en toda tarea | `task_soft_time_limit=1800` s (lanza `SoftTimeLimitExceeded` dentro de la tarea) y `task_time_limit=1920` s (mata el proceso) |

Y además:

- `task_track_started=True`: sin esto, Celery nunca guarda `STARTED` y el estado salta de
  `PENDING` a `SUCCESS`.
- `result_extended=True`: guarda junto al resultado el nombre, los argumentos y el **número de
  reintentos**, que `GET /tasks` devuelve como `attempt`.
- `visibility_timeout` = time limit + 30 min. Es el tiempo que Redis espera un ACK antes de
  reentregar un mensaje. Si fuese menor que la tarea más larga, Redis entregaría a otro worker una
  tarea que sigue en marcha, y se ejecutaría dos veces.
- `task_publish_retry_policy` corta y timeouts de socket de 2-5 s: si Redis no responde, encolar
  falla rápido (503) en vez de colgar la petición.

### 5.2 `TrackedTask`: reintentos, logs y DLQ en una clase base

Toda tarea se declara con `base=TrackedTask` ([services/tasks/base.py](services/tasks/base.py)) y
hereda, sin escribir nada más:

- **Reintentos**: cualquier excepción se reintenta hasta `max_retries = 3` veces, salvo
  `dont_retry_on` (errores que fallarían igual cada vez) y el timeout. La espera es
  `CELERY_RETRY_BACKOFF_SECONDS * 2**reintento`, por defecto **10, 20 y 40 s**. No uso el
  `retry_jitter` de Celery: su «full jitter» elige una espera al azar entre 0 y el countdown, y
  podría reintentar casi al instante, que es justo lo que el ticket prohíbe.
- **Logs**: una línea al empezar cada intento y otra al acabar:

  Líneas reales de la prueba en Docker (recortadas por la derecha):

  ```
  task=reporting.run_weekly_performance_pipeline task_id=d20fa401-… attempt=1/4 status=started
  task=reporting.run_weekly_performance_pipeline task_id=d20fa401-… attempt=1/4 status=success duration_ms=23047
  task=reporting.run_weekly_performance_pipeline task_id=9162e45b-… attempt=1/4 status=retry duration_ms=6556 next_retry_in_s=10 error=PipelineStageError: …
  task=reporting.run_weekly_performance_pipeline task_id=9162e45b-… attempt=2/4 status=success duration_ms=2940
  task=reporting.run_weekly_performance_pipeline task_id=071bfc6c-… attempt=4 status=dead_letter registrada en task_dead_letters
  ```

  El fallo definitivo tiene la misma forma (`attempt=4/4 status=failure duration_ms=… error=<tipo>: <mensaje>`)
  seguida del traceback completo.

  La fecha la pone el formato de Celery (`[2026-11-19 17:23:39,017: ERROR/ForkPoolWorker-1]`). Los
  `retry` y `failure` llevan el traceback completo.
- **DLQ**: si el último intento también falla, o el error no se reintenta, la tarea se escribe en
  `task_dead_letters` **antes** de que Celery guarde `FAILURE` (§10.2). Si la base no responde, se
  intenta 3 veces. Si sigue sin responder, la fila entera queda en un log `CRITICAL`
  (`status=dead_letter_unrecorded`), para no perderla del todo.

`attempt` cuenta ejecuciones: el primer intento es `1/4` y, con `max_retries=3`, el último es `4/4`.

### 5.3 La tabla `task_dead_letters`

[services/tasks/sql/001_task_dead_letters.sql](services/tasks/sql/001_task_dead_letters.sql):

| Columna | Qué guarda |
|---|---|
| `task_id` (único) | El id de Celery, el mismo que devolvió el `202` |
| `task_name` | `reporting.run_weekly_performance_pipeline` |
| `attempt` / `max_retries` | Intento en el que murió (4) y el máximo de reintentos (3) |
| `error_type` / `error_message` | Clase del error y **traceback completo** |
| `args` / `kwargs` | Los argumentos (identificadores) para relanzarla a mano |
| `queue` / `worker` | Cola y hostname del worker |
| `failed_at` / `created_at` | Cuándo falló el último intento y cuándo se escribió la fila |

RLS activado, igual que en `job_runs` y `telemetry_events`. La tabla la crea el propio worker la
primera vez que la necesita, dentro de un advisory lock (§10.4), y también se puede pegar en el SQL
Editor de Supabase. Usa `TASKS_DATABASE_URL` o, si no está, `DATABASE_URL`.

---

## 6. Fase 3 — La operación pesada se convierte en tarea

### 6.1 La tarea

[services/tasks/reporting.py](services/tasks/reporting.py):

```python
@app.task(bind=True, base=TrackedTask, name="reporting.run_weekly_performance_pipeline",
          dont_retry_on=(ValueError, SoftTimeLimitExceeded))
def run_weekly_performance_pipeline(self, week_start=None, lookback_weeks=None, triggered_by=None):
    from data.pipelines import pipeline          # Prefect y Pandas solo en el worker
    summary = pipeline.weekly_warehouse_client_performance_flow(
        week_start=..., lookback_weeks=..., trigger="manual", triggered_by=triggered_by)
    return json.loads(json.dumps(summary, default=str))   # fechas/UUID como texto para Redis
```

- **Mensaje ligero**: `{"week_start": "2026-11-16", "lookback_weeks": 0, "triggered_by": "<id
  admin>"}`, menos de 200 bytes. El worker lee él mismo los eventos de la base. Hay un test que
  intercepta el mensaje y comprueba que no lleva nada más.
- El flow es el **mismo** que antes ejecutaban las BackgroundTasks: escribe `reporting.pipeline_runs`
  con `trigger=manual` y `triggered_by` igual al admin, como en los hitos 19-20.
- Un fallo de etapa (`PipelineStageError`) se reintenta. Un `ValueError` (fecha inválida) no.

### 6.2 El endpoint

```
POST /reporting/pipeline-runs   {"week_start": "2026-11-16", "lookback_weeks": 1}
→ 202 Accepted
  Location: /tasks/b8ad150b-7af6-4c06-b257-8f462cf7be4f
  {"pipeline_name": "weekly_warehouse_client_performance", "status": "scheduled", "mode": "celery",
   "task_id": "b8ad150b-7af6-4c06-b257-8f462cf7be4f", "flow_run_id": null}
```

Antes de encolar sigue validando lo mismo que antes: lunes, semana no futura, `lookback_weeks` en
rango, y **409 si ya hay una corrida en curso** en `reporting.pipeline_runs`. Si Redis no responde
devuelve **503**.

[trigger.py](data/pipelines/weekly_warehouse_client_performance/trigger.py) tiene ahora dos modos:
`celery` (por defecto) y `deployment` (Prefect). `data/pipelines` **no importa Celery**: la API le
pasa la función que encola (`enqueue`), igual que antes le pasaba `background_tasks.add_task`.

**El modo `local` desaparece.** Mantenerlo dejaría abierta la puerta a ejecutar el ETL dentro de la
API, que es lo que el ticket quiere eliminar. Quien tenga `REPORTING_TRIGGER_MODE=local` recibe un
503 que explica el cambio, no un fallo silencioso.

### 6.3 El registro de tareas

Celery responde `PENDING` para **cualquier** id, también para uno inventado: no distingue «en
cola» de «no existe». Por eso la API guarda en Redis, **antes** de publicar el mensaje, una entrada
`trackflow-task-registry-<task_id>` con el dueño y la hora, con la misma caducidad que el
resultado (24 h). Así, `GET /tasks/{id}` responde 404 a los ids que no encoló y a las tareas de otros
usuarios ([services/tasks/registry.py](services/tasks/registry.py)).

Es una clave aparte del resultado de Celery a propósito. Si la API escribiese `PENDING` en
`celery-task-meta-<id>`, podría pisar un `STARTED` que el worker ya hubiese guardado.

---

## 7. Fase 4 — `GET /tasks/{task_id}`

[services/tasks/router.py](services/tasks/router.py). Hace una sola lectura de Redis y nunca espera
a la tarea:

```json
{"task_id": "8c27a091-…", "status": "success",
 "result": {"run_id": "cc31aa2f-…", "weeks_processed": ["2026-11-09", "2026-11-16"],
            "events_extracted": 7, "rows_upserted": 3, "status": "completed", "warnings": […]},
 "error": null, "attempt": 1, "max_attempts": 4,
 "task_name": "reporting.run_weekly_performance_pipeline",
 "enqueued_at": "2026-11-19T17:17:29.740492+00:00", "finished_at": "2026-11-19T17:17:50.357245+00:00"}
```

| Estado de Celery | `status` | Cuándo |
|---|---|---|
| `PENDING`, `RECEIVED` | `pending` | En la cola, o reservada por un worker que aún no la empezó |
| `STARTED` | `started` | Un worker la está ejecutando |
| `RETRY` | `retry` | Falló y espera su backoff (§13) |
| `SUCCESS` | `success` | Terminó; `result` lleva lo que devolvió |
| `FAILURE`, `REVOKED` | `failure` | Agotó los reintentos (está en la DLQ) o se canceló; `error` lleva el motivo |

- `result` solo aparece en `success`. `error` aparece en `failure` y `retry`.
- 401 sin sesión. 404 si el id no existe o es de otro usuario (salvo admin). 503 si Redis no
  responde.
- Responde en unos 2 ms (medido en los logs de Uvicorn).

---

## 8. Fase 5 — Worker y Flower en Docker

```yaml
worker:
  build: { context: ./services }          # la misma imagen que el backend…
  command: [celery, -A, services.celery_app, worker, --loglevel=INFO, --concurrency=2]   # …otro proceso
  stop_grace_period: 2m
  environment: { REDIS_URL: redis://redis:6379/0, DATABASE_URL, PYTHONPATH: /app, … }

flower:
  command: [celery, -A, services.celery_app, flower, --port=5555]
  ports: ["5555:5555"]
```

- **El worker es otro contenedor**, con la misma imagen y las mismas dependencias que el backend,
  pero arranca `celery worker`, no Uvicorn. Parar o reiniciar el backend no lo toca (§11.2).
- **Parada en caliente**: `docker compose stop worker` manda SIGTERM. Celery deja de aceptar
  tareas y termina la que tiene en curso. `stop_grace_period: 2m` le da margen antes del SIGKILL.
  Si llega el SIGKILL, el mensaje no se pierde: no tenía ACK, y Redis lo reentrega.
- `PYTHONPATH=/app`: ver §10.3.
- `worker_send_task_events` y `task_send_sent_event` en `celery_app`: sin eventos, Flower solo vería
  los workers, no las tareas.
- **Flower** en `http://localhost:5555`, sin autenticación. Es solo para desarrollo:
  `FLOWER_UNAUTHENTICATED_API` deja leer su API JSON con `curl`. Ese puerto no se publica en
  producción.

---

## 9. Cuándo hice commit y por qué

La regla es la misma que en el hito 21: **un commit por cada pieza que funciona por sí sola, con sus
tests en verde y la suite completa pasando**. Cada commit deja la rama en un estado que se puede
probar, revisar y revertir sin arrastrar nada más. Además, este hito añade una regla: **cada bug
encontrado al probar va en su propio commit `fix:`**, con el porqué en el mensaje, en vez de
esconderlo dentro de la fase siguiente.

| # | Commit | Momento | Por qué ahí |
|---|---|---|---|
| 1 | `16bf65f` feat(infra): Redis y dependencias | Con Redis levantado en Docker y comprobado (`maxmemory-policy noeviction`, `appendonly yes`) | Es la base de todo y no depende de nada. Va antes del código porque el paso 5 del README pide ver un worker conectado al broker antes de tocar endpoints, y para eso Redis tiene que existir. Separar dependencias e infraestructura también deja revisar el `uv.lock` sin código alrededor |
| 2 | `6221ceb` feat(tasks): Celery, `TrackedTask` y DLQ | Con los 17 tests del worker real en verde (reintentos, backoff, DLQ, logs) y la suite completa (1146) | Es la maquinaria genérica: vale para cualquier tarea, no solo para el pipeline. Aislada, se ve que los reintentos y la DLQ se prueban con tareas de juguete, sin el ETL de por medio. Justo después levanté un worker real contra el Redis de Docker (`celery inspect ping` → `pong`), como pide el README, **antes** de tocar ningún endpoint |
| 3 | `0b420db` feat(reporting): el endpoint encola y responde 202 | Con el flow real ejecutado por un worker en los tests y la suite completa (1152) | Es el cambio de comportamiento visible: la operación pesada sale de la API. Incluye la tarea, el registro, el cambio de `trigger.py` y la retirada del modo `local`. Separados, dejarían commits con una tarea que nadie encola o un endpoint que encola algo inexistente |
| 4 | `f817e3e` fix(tasks): DLQ antes de `FAILURE` | En cuanto un test intermitente de la suite completa destapó la carrera (§10.2) | Es un bug de la fase 2 con su propia explicación. Mezclarlo con la fase 4 escondería por qué `__call__` gestiona el fallo definitivo en vez de `on_failure` |
| 5 | `e010b51` feat(tasks): `GET /tasks/{task_id}` | Con los 10 tests del ciclo de vida (cada estado visto a través del endpoint) y la suite completa (1162) | El endpoint de consulta es independiente de cómo se encola: va solo, con su propio contrato |
| 6 | `e522843` fix(tasks): DLQ con varios procesos | Tras la prueba e2e en Docker, donde se perdió una fila de la DLQ (§10.4) | Otro bug distinto, y solo se ve con PostgreSQL y varios procesos: los tests con SQLite y un hilo no podían destaparlo. Commit propio para que el advisory lock tenga su explicación |
| 7 | `855ab78` perf(api): calentar Redis al arrancar | Tras medir 380 ms en el primer POST en Docker y 34 ms después del cambio (§10.5) | Es una mejora de rendimiento con su medición. Va aparte porque toca el `lifespan` de la API, y quien revise el hito 21 (que prohibía programar trabajo en el lifespan) tiene que ver que aquí solo se abren conexiones |
| 8 | `3ed42e0` feat(infra): worker y flower | Después de la prueba e2e completa con los dos servicios | La infraestructura de ejecución se validó al final, con todo lo anterior funcionando, e incluye la corrección de `PYTHONPATH` que esa prueba destapó. Va después de los dos `fix` porque estos tocan código que ya estaba commiteado y no dependen del compose |
| 9 | `484b598` docs(readme): el worker | Con el comportamiento real ya medido | El checklist pide documentar en el README cómo levantar y detener el worker. Va aparte de este documento porque es la documentación permanente del monorepo, no la del hito |
| 10 | docs: hito 22 | Al final | Cita los hashes y las mediciones reales, así que solo se puede escribir cuando ya existen |

Antes de los commits 2, 3, 4 y 5 lancé `uv run pytest -q` completo (unos 4 minutos). El commit 1 no
tiene código: lo comprobé levantando Redis. Antes de los commits 6 y 7 lancé solo `tests/tasks` (35
tests), y la suite completa (1170) justo después, antes del commit 8. Lo que **no** hice: un
commit por archivo (dejaría commits rotos, como una tarea que importa un registro que aún no
existe) ni un commit gigante al final (impediría revertir, por ejemplo, el calentamiento sin
perder la DLQ).

---

## 10. Problemas que aparecieron y cómo se resolvieron

### 10.1 Celery cambia el tipo de la excepción

En la DLQ apareció `error_type = RuntimeError` en vez de `PipelineStageError`. Con el serializador
JSON, Celery entrega a `on_retry` y `on_failure` una **copia reconstruida** de la excepción, y ni
`exc` ni `einfo.type` conservan la clase original. **Solución:** `TrackedTask.__call__` captura la
excepción real y guarda su nombre. La DLQ y los logs dicen `PipelineStageError`.

### 10.2 `FAILURE` visible antes de que exista la fila de la DLQ

Un test pasaba aislado y fallaba de vez en cuando en la suite completa: «la tarea está en
`FAILURE`, pero no hay fila en la DLQ ni línea de log». Celery guarda `FAILURE` en Redis **antes**
de llamar a `on_failure`, así que durante unos milisegundos `GET /tasks` podía decir `failure`
sin que la DLQ tuviese la tarea. **Solución:** el fallo definitivo (log y DLQ) se gestiona en
`__call__`, antes de relanzar la excepción. `on_failure` queda como red de seguridad. Ahora, cuando
la API dice `failure`, la fila ya existe.

### 10.3 `ModuleNotFoundError: No module named 'data'` en el worker de Docker

La primera prueba en Docker falló en los cuatro intentos de las tres tareas. Celery añade el
directorio actual a `sys.path` **solo mientras carga la app** y luego lo quita. Como la tarea importa
`data.pipelines` dentro de la función, ese import llega tarde. Los tests no podían verlo, porque
pytest corre con la raíz del repo en el path. **Solución:** `PYTHONPATH=/app` en el worker y en
Flower. El mismo problema apareció en el hito 21 con el seed del e2e.

Lo bueno es que esa prueba fallida sirvió de demostración real de la DLQ: las tres tareas
recorrieron sus 4 intentos (10, 20, 40 s) y acabaron en `failure`.

### 10.4 Dos procesos del worker crean la tabla a la vez

En esa misma prueba, de las 3 tareas fallidas solo 2 quedaron en `task_dead_letters`. Los dos
procesos del worker (`--concurrency=2`) fallaron en el mismo instante, y los dos ejecutaron
`create table if not exists`. En PostgreSQL esa sentencia **no es segura con concurrencia**: el
segundo chocó en el catálogo (`duplicate key value violates unique constraint
"pg_type_typname_nsp_index"`). La fila no se perdió del todo, porque quedó en el log `CRITICAL`
con todos sus datos, pero la DLQ tiene que ser fiable. **Solución:**

- el DDL va dentro de `pg_advisory_xact_lock`, así que el segundo proceso espera al primero y
  después no hace nada;
- el DDL se ejecuta una vez por proceso;
- la escritura de la DLQ se intenta hasta 3 veces.

Repetí la prueba con la tabla borrada y dos tareas fallando a la vez, y quedaron las dos filas.

### 10.5 El primer `202` tras arrancar tardaba 380 ms

Medido en Docker: 387 ms el primer POST y 10-24 ms los siguientes. El ticket pide menos de 200 ms
siempre. Al perfilar el camino en frío salió:

| Paso | Frío | Caliente |
|---|---|---|
| Crear el cliente Redis del backend de resultados | 76 ms | 0 ms |
| Primera conexión a la base (comprobación del 409) | 24 ms | 3 ms |
| Primer `apply_async` (pool del productor) | 12 ms | 2 ms |

**Solución:** `warm_up_task_queue()` en el `lifespan` de la API hace `ping` al backend y abre la
conexión del productor. Tras el cambio, el primer POST después de reiniciar la API tarda **34 ms**
y los siguientes **12-15 ms** (10,6 ms dentro de la API, según su log de tiempos). Si Redis está
caído al arrancar, la API arranca igual, con un aviso.

### 10.6 Tres corridas solapadas

En la prueba lancé sin querer tres POST seguidos. El 409 no saltó: protege contra una corrida
**ya empezada** (fila `running` en `reporting.pipeline_runs`), y las tres se encolaron antes de que
ninguna empezase. Volvió a pasar, ya con la tarea funcionando, con las 5 corridas que encolé al
medir el calentamiento (§10.5) con el worker parado. Al arrancar el worker, una ejecutó el
pipeline, y las otras cuatro chocaron con el lock del pipeline (`PipelineAlreadyRunning`, del hito
19), esperaron su backoff de 10 y 20 s y terminaron en `success`. El pipeline es idempotente (UPSERT
por semana), así que repetir la corrida no duplica nada. Está en §13.

### 10.7 Las revocaciones se pierden al recrear el worker

Para perfilar encolé 2 tareas con una espera de 1 h y las revoqué. Al recrear el contenedor del
worker volvieron a aparecer en Flower como `RECEIVED`. Celery guarda la lista de revocadas **en la
memoria del worker**, y el mensaje sin ACK volvió a la cola. Las revoqué otra vez y, al final,
vacié el Redis de la prueba. Para producción haría falta `--statedb` (§14).

---

## 11. Cómo se comprobó

### 11.1 Tests automáticos

```
uv run pytest tests/tasks -q     # 39 passed
uv run pytest -q                 # 1170 passed (toda la suite)
```

Los tests de `tests/tasks/` arrancan un **worker real de Celery** en un hilo
(`celery.contrib.testing.worker.start_worker`), con el broker `memory://` y el backend
`cache+memory://`. Los mensajes pasan por un broker de verdad y los reintentos esperan su
countdown como en producción. Solo cambia el transporte. El conftest global fija esas URLs, así que
ningún test habla con un Redis real.

| Archivo | Qué prueba |
|---|---|
| `test_celery_app.py` (9) | `REDIS_URL`, las tres reglas en la configuración, que `celery_app` no importa FastAPI, columnas e índices de la DLQ, migración SQL, `TASKS_DATABASE_URL`, el DDL una vez por motor y tras el advisory lock, la API arranca sin Redis |
| `test_tracked_task.py` (12) | Éxito sin reintentos, reintento hasta funcionar, **backoff creciente medido** entre intentos, 10/20/40 s por defecto, DLQ tras 4 intentos con traceback y argumentos, error no reintentable directo a la DLQ, una fila por tarea, base caída (log CRITICAL), corte breve (reintento de escritura), **formato de log** por intento y error completo en los fallos |
| `test_pipeline_task.py` (4) | La tarea registrada con `max_retries=3`, **el endpoint encola y el worker ejecuta el flow real** (Prefect + SQLite) y alimenta los otros dos endpoints de reporting, pipeline que sigue fallando → DLQ con `PipelineStageError` e intento 4, parámetro inválido sin reintento |
| `test_tasks_endpoint.py` (10) | `pending`, `started`, `retry`, `success` (con resultado), `failure` (con error), **el ciclo completo** visto solo por el endpoint, 404 para ids desconocidos o inválidos, 404 para tareas de otro usuario pero visible para admin, 401, 503 |
| `test_compose.py` (4) | Redis oficial, puerto 6379, `noeviction` y `appendonly`; la misma `REDIS_URL` en backend, worker y Flower; el worker ejecuta `celery`, no `uvicorn`; Flower en 5555 |
| `tests/reporting/test_reporting_endpoints.py` | 202 con `task_id`, `mode: celery` y `Location`; valores por defecto; **el mensaje solo lleva identificadores** (< 200 bytes); 503 si Redis no responde; el modo `local` rechazado; 409 y 422 sin encolar nada |

### 11.2 Prueba end-to-end en Docker

Entorno: los servicios `redis`, `backend`, `worker` y `flower` del compose, con un PostgreSQL 17
desechable en la red `trackflow-net`, el esquema real de la API y 7 eventos sembrados. El Supabase
del `.env` sigue sin responder (`tenant/user … not found`, igual que en el hito 21). El admin de
prueba se creó en una TinyDB desechable del contenedor, sin tocar `services/api/db.json`.

1. **El worker se conecta al broker**: `Connected to redis://…@redis:6379/0`, con
   `reporting.run_weekly_performance_pipeline` en su lista de tareas. Antes, en Windows,
   `celery inspect ping` contra el Redis de Docker → `pong`.
2. **202 en menos de 200 ms**: el primer POST tras arrancar tardó 34 ms y los siguientes 12-15 ms
   (10,6 ms dentro de la API). Antes del calentamiento, 387 ms el primero (§10.5).
3. **Ciclo completo con éxito**: `started` → `success` en ~20 s, con el resumen del pipeline como
   `result` (7 eventos, 3 filas, semanas 2026-11-09 y 2026-11-16).
4. **`pending`**: con el worker parado, `GET /tasks/{id}` → `pending` y 7 mensajes en la lista
   `celery` de Redis.
5. **Parar la API no pierde mensajes ni para el worker**: con la API parada seguía habiendo 7
   mensajes en Redis. Arranqué el worker con la API aún parada, y procesó todo hasta dejar 0
   mensajes: las 5 corridas acabaron en `success`, cuatro tras reintentar por el lock (§10.6).
6. **Reintentos con backoff y DLQ**: arranqué el worker con una contraseña de escritura incorrecta
   y `CELERY_RETRY_BACKOFF_SECONDS=2`, y lancé 2 tareas a la vez con la tabla de la DLQ borrada.
   Vistos desde `GET /tasks`: `started` → `retry` → … → `failure` con `attempt: 4`. Las esperas
   entre un `retry` y el `started` siguiente fueron de **2, 4 y 8 s**. En PostgreSQL:

   ```
    task     | attempt | max_retries |     error_type     |                       error
   ----------+---------+-------------+--------------------+-------------------------------------------------------
    071bfc6c |       4 |           3 | PipelineStageError | FATAL:  password authentication failed for user "postgres"
    73c91407 |       4 |           3 | PipelineStageError | FATAL:  password authentication failed for user "postgres"
   ```

   Las dos filas existen aunque la tabla no existía y los dos procesos fallaron en el mismo segundo.
7. **Flower**: `http://localhost:5555` → 200. Su API mostraba el worker conectado y las tareas: 6
   `SUCCESS` y 2 `FAILURE`.
8. **Parada en caliente**: `docker compose stop worker` con una tarea en `started`. La tarea
   terminó en `success` antes de que el contenedor se detuviese.

Al terminar paré los servicios, vacié el Redis de la prueba y eliminé el PostgreSQL desechable.

---

## 12. Cómo arrancarlo y probarlo

```bash
docker compose up -d redis backend worker flower
docker compose logs -f worker

# 1. Token de un admin (POST /auth/login) y encolar
curl -i -X POST http://localhost:8000/reporting/pipeline-runs \
     -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
     -d '{"week_start":"2026-11-16","lookback_weeks":0}'
# → HTTP/1.1 202 Accepted, Location: /tasks/<task_id>, {"task_id": "...", ...}

# 2. Consultar el estado (repetir)
curl -s http://localhost:8000/tasks/<task_id> -H "Authorization: Bearer $TOKEN"

# 3. Flower
open http://localhost:5555

# 4. Ver la DLQ
psql "$DATABASE_URL" -c "select task_id, task_name, attempt, error_type, failed_at from task_dead_letters order by failed_at desc;"

# 5. Forzar fallos para ver reintentos y DLQ (solo en local)
REPORTING_WRITER_DATABASE_URL=postgresql://postgres:mal@host/db CELERY_RETRY_BACKOFF_SECONDS=2 \
  docker compose up -d worker

# Detener el worker (parada en caliente)
docker compose stop worker
```

Sin Docker: `uv run celery -A services.celery_app worker --loglevel=INFO --pool=solo` (Windows) o
sin `--pool=solo` (Linux/macOS). El resto está en el [README](README.md).

---

## 13. Decisiones discutibles (y cómo defenderlas)

**«`status` tiene un quinto valor, `retry`.»** El ticket lista cuatro estados y pide que
reflejen «los estados reales de Celery». Mientras una tarea espera su backoff, su estado real en
Celery es `RETRY`. Mostrarla como `pending` escondería que ya falló, y como `started` mentiría,
porque nadie la está ejecutando. Los cuatro estados del ticket están todos, con el mismo
significado. `retry` añade la fase que el propio ticket introduce con los reintentos.

**«`max_retries=3` son cuatro ejecuciones.»** El checklist fija `max_retries=3`, y en Celery eso
significa 1 intento más 3 reintentos. La DLQ guarda `attempt: 4` y `max_retries: 3`, así que no
hay ambigüedad sobre lo que pasó. Para que entren tras «tres fallos» exactos bastaría con
`max_retries=2`, pero contradiría el valor explícito del checklist.

**«La DLQ es una tabla, no una cola de Redis.»** El checklist pide registrar en base de datos
`task_id`, intento, error y timestamp. Una tabla sobrevive a que Redis caduque los resultados
(24 h), se consulta con SQL y se puede cruzar con `reporting.pipeline_runs`. Guarda los argumentos,
así que relanzar una tarea es un `apply_async` con ellos.

**«El timeout no se reintenta.»** Una tarea que ya consumió sus 30 minutos tardaría lo mismo en el
siguiente intento. Reintentarla bloquearía el worker dos horas antes de llegar a la DLQ. Va
directa a la DLQ (`dont_retry_on=SoftTimeLimitExceeded`).

**«Se eliminó el modo `local`.»** Era la vía por la que el ETL corría dentro de la API. Dejarlo
como opción permitiría volver a ese estado sin darse cuenta. Sin Redis, el endpoint responde 503
con un mensaje claro. Para lanzar el pipeline sin cola sigue existiendo la CLI
(`python data/pipelines/pipeline.py`).

**«Hay código en el `lifespan` de FastAPI, y el hito 21 lo prohibía.»** El hito 21 prohibía
**programar o ejecutar** trabajo en el lifespan (APScheduler, `@repeat_every`). Aquí el lifespan
solo abre dos conexiones con Redis. No encola, no ejecuta y no programa nada, y si falla, la API
arranca igual.

**«El 409 no evita del todo las corridas duplicadas.»** Comprueba si hay una corrida **empezada**.
Dos POST en el mismo segundo se encolan los dos. El segundo choca en el worker con el lock del
pipeline y se reintenta con backoff. Como el pipeline es idempotente, la segunda corrida recalcula
lo mismo sin duplicar nada (§10.6). Cerrarlo del todo exigiría un lock en Redis al encolar, que
duplicaría el que ya tiene `reporting.pipeline_runs`.

**«El registro de tareas guarda más estado en Redis.»** Es una clave por tarea, de menos de 200
bytes, que caduca con el resultado. A cambio, `GET /tasks` distingue «no existe» de «en cola» y
nadie ve las tareas de otro usuario.

---

## 14. Lo que queda pendiente

- **Supabase**: el del `.env` sigue sin responder. Cuando vuelva, `task_dead_letters` se creará sola
  la primera vez que una tarea acabe en la DLQ, o se puede pegar
  [la migración](services/tasks/sql/001_task_dead_letters.sql) en el SQL Editor.
- **Revocaciones persistentes**: `--statedb` en el worker, con un volumen, para que una tarea
  cancelada no reaparezca al reiniciar el worker (§10.7).
- **Worker sin root**: Celery avisa de que corre como root. Se arregla con un `USER` en la imagen.
  Es la misma imagen que el backend, así que conviene hacerlo para los dos a la vez.
- **`error` en `GET /tasks`**: muestra el tipo reconstruido por Celery (`RuntimeError: start: …`).
  El mensaje es el correcto, y el tipo real está en la DLQ.
- **SIGKILL a mitad de tarea**: el mensaje vuelve a la cola cuando pasa el `visibility_timeout`
  (unas 2,5 h), no al instante. Es el precio de no ejecutar dos veces una tarea larga.
- **Time limits en Windows**: con `--pool=solo` (el único que funciona en Windows) Celery no aplica
  `soft/hard time limit`. En Docker (Linux, prefork) sí.
- **Backoffice**: ninguna pantalla usa todavía `POST /reporting/pipeline-runs` ni `GET /tasks`.
- **PR**: no he hecho push ni abierto el PR. Este hito va encima del 21; conviene fusionar antes
  el PR del 21.

---

## 15. Cuerpo del PR

```markdown
## Ticket #DEV-55 — Cola de tareas asíncronas con Redis y Celery

La operación más pesada de la API, `POST /reporting/pipeline-runs` (el ETL semanal), ya no corre
en el proceso de FastAPI: se encola en Redis, responde `202` con `task_id` en ~15 ms y la ejecuta
un worker de Celery en su propio contenedor. El estado se consulta en `GET /tasks/{task_id}`.

### Qué incluye
- **Redis** (imagen oficial, 6379, `noeviction`, `appendonly`) como broker y backend de resultados;
  la API, el worker y Flower usan la misma `REDIS_URL`.
- **`services/celery_app.py`**: JSON, `acks_late` + `reject_on_worker_lost`, prefetch 1, time limit
  30/32 min, `visibility_timeout` mayor que el time limit.
- **`TrackedTask`**: `max_retries=3` con backoff exponencial 10/20/40 s (sin jitter: nunca
  inmediato), log por intento (`task_id`, `attempt`, `status`, `duration_ms`, traceback en
  fallos) y **DLQ** en la tabla `task_dead_letters` (task_id, intento, error completo, args,
  worker, timestamp) al agotar reintentos.
- **`POST /reporting/pipeline-runs`** → `202 {task_id}` + `Location: /tasks/{id}`; el mensaje solo
  lleva `week_start`, `lookback_weeks` y `triggered_by`. El modo `local` (BackgroundTasks) se
  elimina.
- **`GET /tasks/{task_id}`** → `pending | started | retry | success | failure`, `result`, `error`,
  `attempt`. 404 para ids desconocidos o de otros usuarios.
- **docker-compose**: servicios `redis`, `worker` (`celery worker`, no Uvicorn) y `flower`
  (http://localhost:5555). README con cómo levantar y detener el worker.

### Pruebas
- `uv run pytest -q` → 1170 passed (39 nuevos en `tests/tasks/`, con un worker de Celery real).
- E2E en Docker con PostgreSQL: 202 en 34 ms en frío / 12-15 ms en caliente; ciclo
  pending → started → success; reintentos a los 2, 4 y 8 s (base 2 s) y DLQ con intento 4;
  API parada sin perder mensajes; Flower con tareas completadas y fallidas; parada en caliente.

Detalle, decisiones y commits: `hito_22.md`.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

---

## 16. Archivos creados y modificados

| Archivo | Cambio |
|---|---|
| `services/celery_app.py` | Nuevo: instancia y configuración de Celery |
| `services/tasks/__init__.py` | Nuevo: mapa del paquete |
| `services/tasks/base.py` | Nuevo: `TrackedTask` (reintentos, backoff, logs, DLQ) |
| `services/tasks/dead_letters.py` | Nuevo: tabla `task_dead_letters` y sus funciones |
| `services/tasks/sql/001_task_dead_letters.sql` | Nuevo: migración PostgreSQL |
| `services/tasks/registry.py` | Nuevo: registro de tareas encoladas (dueño, hora) |
| `services/tasks/reporting.py` | Nuevo: tarea del pipeline y función que la encola |
| `services/tasks/router.py` | Nuevo: `GET /tasks/{task_id}` y calentamiento de Redis |
| `services/reporting/router.py`, `schemas.py` | `POST /pipeline-runs` encola: `task_id`, `mode: celery`, `Location` |
| `data/pipelines/weekly_warehouse_client_performance/trigger.py` | Modo `celery` por defecto; fuera el modo `local` |
| `data/pipelines/PIPELINE_DESIGN.md` | Nota del cambio de modo |
| `services/api/main.py` | Router de `/tasks` y calentamiento en el lifespan |
| `docker-compose.yml` | Servicios `redis`, `worker`, `flower`; `REDIS_URL` en el backend; `REPORTING_TRIGGER_MODE=celery` |
| `.env.example` | `REDIS_URL`, `REDIS_URL_DOCKER`, `TASKS_DATABASE_URL`, `CELERY_*`, `FLOWER_PORT` |
| `pyproject.toml`, `uv.lock`, `services/requirements.txt` | `celery`, `redis`, `flower` |
| `README.md` | Sección «Cola de tareas»: levantar y detener el worker |
| `tests/conftest.py` | Broker y backend en memoria para todos los tests |
| `tests/tasks/*` | Nuevos: 39 tests y las tareas de prueba (`sample_tasks.py`) |
| `tests/reporting/test_reporting_endpoints.py` | Tests del endpoint en modo Celery |
| `tests/test_api_characterization.py` | La ruta nueva en la foto de rutas de la API |

---

## 17. Checklist de evaluación

**Infraestructura**
- [x] Redis en `docker-compose.yml`, imagen oficial, puerto `6379`, `noeviction` → §4
- [x] Flower en `docker-compose.yml`, puerto `5555` → §8
- [x] API y workers usan el mismo Redis vía `REDIS_URL` → §4, test `test_api_worker_and_flower_share_the_same_redis_url`

**Módulo Celery**
- [x] Instancia con Redis como broker y backend → §5.1
- [x] Tarea `@app.task` con la operación pesada → §6.1
- [x] `max_retries=3` con backoff exponencial → §5.2, medido en §11.2 (2, 4, 8 s)
- [x] DLQ en base de datos con `task_id`, intento, error y timestamp → §5.3, §11.2

**Endpoints**
- [x] El endpoint encola y devuelve `202 {"task_id": ...}` al instante → §6.2 (34 ms en frío, 12-15 ms en caliente)
- [x] `GET /tasks/{task_id}` → `{"task_id", "status", "result"}` → §7
- [x] `status` con los estados reales de Celery → §7, §13

**Worker**
- [x] Proceso independiente de FastAPI → §8, §11.2 (punto 5)
- [x] Documentado en el README: levantarlo y detenerlo → [README](README.md)

**Observabilidad**
- [x] Log por tarea con `task_id`, intento, estado y duración → §5.2
- [x] Los fallos registran el error completo → §5.2 (traceback en el log y en la DLQ)
- [x] Flower muestra tareas encoladas, en curso, completadas y fallidas → §11.2 (punto 7)

**Qué se evalúa**
- [x] Redis en Docker y workers conectados sin errores → §11.2 (punto 1)
- [x] 202 con `task_id` en < 200 ms → §10.5, §11.2 (punto 2)
- [x] `GET /tasks` correcto en cada fase → §11.1 (`test_tasks_endpoint.py`), §11.2
- [x] Backoff: nunca se reintenta al instante → §5.2, §11.2 (punto 6)
- [x] Tras los fallos, la tarea en la DLQ con `task_id`, intento y error → §11.2 (punto 6)
- [x] Parar la API no para el worker ni pierde mensajes → §11.2 (punto 5)
- [x] Mensajes solo con identificadores → §6.1, test `test_manual_run_puts_only_identifiers_in_the_message`
- [x] Flower con al menos una tarea completada y una fallida → §11.2 (punto 7)

---

## 18. Glosario

| Término | Significado |
|---|---|
| **Broker** | Intermediario donde esperan los mensajes hasta que un worker los toma (Redis) |
| **Backend de resultados** | Donde el worker guarda el estado y el resultado de cada tarea (también Redis) |
| **Productor / consumidor** | Quien encola el trabajo (la API) / quien lo ejecuta (el worker) |
| **Worker** | Proceso de Celery que escucha la cola y ejecuta las tareas |
| **ACK** | Confirmación de que un mensaje se procesó; con `acks_late`, al terminar la tarea |
| **Prefetch** | Mensajes que un worker reserva por adelantado; aquí 1 |
| **Backoff exponencial** | Esperas crecientes entre reintentos (10, 20, 40 s) |
| **Jitter** | Variación aleatoria de la espera; aquí no se usa porque podría dar esperas de casi 0 |
| **DLQ (Dead Letter Queue)** | Registro de las tareas que agotaron sus reintentos: `task_dead_letters` |
| **Soft / hard time limit** | Timeout que avisa a la tarea (30 min) / que mata el proceso (32 min) |
| **Visibility timeout** | Tiempo que Redis espera un ACK antes de reentregar el mensaje |
| **Parada en caliente (warm shutdown)** | El worker deja de aceptar tareas y termina la que está en curso antes de salir |
| **Advisory lock** | Cerrojo de PostgreSQL por número, sin tabla: aquí serializa el DDL de la DLQ |
| **Flower** | Interfaz web para ver workers y tareas de Celery en tiempo real |
| **`noeviction`** | Política de Redis: con la memoria llena, rechazar escrituras en vez de borrar claves |
| **AOF (`appendonly`)** | Registro en disco de cada escritura de Redis: los datos sobreviven a un reinicio |
