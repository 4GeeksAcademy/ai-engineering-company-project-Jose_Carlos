# Hito 19 — Pipeline de desempeño de negocio: implementación resiliente con Prefect

Este documento explica, desde cero, cómo se ha pasado del **diseño** del hito 18
([data/pipelines/PIPELINE_DESIGN.md](data/pipelines/PIPELINE_DESIGN.md)) a **un pipeline que corre**:
un flow de Prefect que lee `telemetry_events`, calcula los cuatro KPIs del «Reporte Semanal de
Desempeño por Almacén y Cliente» y los deja en `reporting.weekly_warehouse_client_performance`, más
tres endpoints que el dashboard ejecutivo de la Parte 3 podrá consumir. Está pensado para que alguien
que nunca ha usado Prefect termine sabiendo qué hace resiliente a un pipeline, por qué cada task
tiene los reintentos que tiene y qué pasa exactamente cuando algo falla.

Los entregables formales son:

- [data/pipelines/pipeline.py](data/pipelines/pipeline.py): los flows y tasks de Prefect y la CLI
  (`python data/pipelines/pipeline.py`).
- [data/pipelines/weekly_warehouse_client_performance/](data/pipelines/weekly_warehouse_client_performance/):
  la lógica pura (extracción, transformación, carga, log, pasos opcionales, consultas, disparo) y el
  DDL del esquema `reporting` en `sql/001_reporting_schema.sql`.
- [services/reporting/](services/reporting/router.py): los tres endpoints nuevos.
- [data/pipelines/PIPELINE_DESIGN.md](data/pipelines/PIPELINE_DESIGN.md): actualizado; frecuencia y
  comandos en la sección 15, cambios respecto al diseño en la 16.
- Tests: 58 nuevos en [tests/reporting/](tests/reporting/).

Rama: `feature/business-performance-pipeline-impl` (sale de `feature/business-performance-pipeline`,
la del diseño).

Commits, uno por fase:

| Commit | Fase |
|---|---|
| `b94d615` | Fase 1 — Flows y tasks (extracción, transformación, carga y pasos opcionales) |
| `1785c36` | Fase 2 — Resiliencia: reintentos, fallos explícitos y caché |
| `83ef19a` | Fase 3 — Idempotencia y log de ejecución |
| `db95388` | Fase 4 — Ejecución por CLI y backfill |
| `6a679bc` | Fase 5 — Endpoints de `services/reporting/` |

---

## Índice

1. [El encargo](#1-el-encargo)
2. [Conceptos básicos](#2-conceptos-básicos)
3. [Cómo está organizado el código](#3-cómo-está-organizado-el-código)
4. [Fase 1 — Flows y tasks](#4-fase-1--flows-y-tasks)
5. [Fase 2 — Resiliencia](#5-fase-2--resiliencia)
6. [Fase 3 — Idempotencia y log de ejecución](#6-fase-3--idempotencia-y-log-de-ejecución)
7. [Fase 4 — Ejecución como script](#7-fase-4--ejecución-como-script)
8. [Fase 5 — Endpoints del backend](#8-fase-5--endpoints-del-backend)
9. [Problemas que aparecieron y cómo se resolvieron](#9-problemas-que-aparecieron-y-cómo-se-resolvieron)
10. [Cómo se comprobó](#10-cómo-se-comprobó)
11. [Cómo arrancarlo y probarlo](#11-cómo-arrancarlo-y-probarlo)
12. [Decisiones discutibles (y cómo defenderlas)](#12-decisiones-discutibles-y-cómo-defenderlas)
13. [Lo que queda pendiente](#13-lo-que-queda-pendiente)
14. [Archivos creados y modificados](#14-archivos-creados-y-modificados)
15. [Checklist de evaluación](#15-checklist-de-evaluación)
16. [Glosario](#16-glosario)

---

## 1. El encargo

El ticket del tech lead: *«El diseño está aprobado. El liderazgo quiere ver este pipeline corriendo,
no solo documentado.»* Cuatro requisitos no negociables:

1. **Tolerar fallos parciales** sin interrumpir toda la ejecución.
2. **Reintentos** en las tasks que tocan servicios externos.
3. **Ejecutable como script** desde la línea de comandos.
4. **No repetir** una task que ya corrió con éxito en la última hora.

Y las restricciones de siempre: leer `telemetry_events` sin escribir nunca en ella, escribir solo en
la tabla del BRIEFING (`reporting.weekly_warehouse_client_performance`), y que nada del reporte
técnico (`services/telemetry/analysis.py`, `GET /telemetry/report`) cambie.

---

## 2. Conceptos básicos

### Un pipeline resiliente no es uno que nunca falla: es uno que falla bien

En la práctica eso son tres mecanismos de Prefect:

| Mecanismo | Pregunta que responde | En este pipeline |
|---|---|---|
| **Tasks críticas y opcionales** | ¿Este fallo tiene que parar todo? | Extracción, transformación y carga son críticas: sin ellas no hay reporte. La conciliación con `stock_exit` y el snapshot JSON son opcionales: si fallan, se anota un aviso y la corrida termina `Completed` |
| **Reintentos** (`retries`, `retry_delay_seconds`) | ¿Puede arreglarse solo esperando? | Un corte de red con Supabase, sí. Una semana que no es lunes, no: por eso solo se reintentan errores transitorios |
| **Caché** (`cache_key_fn`, `cache_expiration`) | ¿Ya calculé esto hace poco? | La transformación se reutiliza durante una hora si sus eventos de entrada son exactamente los mismos |

### `return_state=True`

Al llamar a una task dentro de un flow, Prefect devuelve su resultado; si la task falla, lanza la
excepción y el flow se cae. Con `return_state=True` devuelve el **State** de la task (`Completed`,
`Failed`…) y es el flow quien decide:

```python
state = export_weekly_snapshot(weekly, weeks, now, return_state=True)
if state.is_failed():
    warnings.append({"step": "export_weekly_snapshot", "error": str(state.message)})  # y seguimos
```

En este pipeline se usa en **todas** las tasks: en las opcionales para seguir adelante, y en las
críticas para saber en qué etapa falló antes de parar (`_require(state, "load")`).

### Clave de caché

Prefect guarda el resultado de una task bajo una **clave**. Si otra llamada produce la misma clave y
el resultado no ha caducado, se devuelve el guardado sin ejecutar la task (estado `Cached`). Todo
depende de qué entra en la clave: si fuera «la fecha de hoy», un evento nuevo no invalidaría nada y el
reporte saldría mal. Aquí la clave es **el contenido** de los datos de entrada.

### Idempotencia, otra vez

El hito 18 lo explicó en detalle; aquí se ha implementado tal cual: totales absolutos de semanas
completas, UPSERT por `unique (warehouse, client_id, week_start)` y una transacción por carga. Correr
el pipeline dos veces deja la tabla idéntica.

### Servidor de Prefect temporal

Prefect guarda el estado de cada corrida en un servidor (su API). Si no hay ninguno configurado
(`PREFECT_API_URL` vacío), al ejecutar un flow levanta uno temporal en local, lo usa y lo apaga al
terminar. Es lo que pasa con `python data/pipelines/pipeline.py`: tarda unos 15 s más en arrancar,
pero no necesita instalar nada aparte.

---

## 3. Cómo está organizado el código

```
data/pipelines/
├── pipeline.py                         # Prefect: tasks, flows, reintentos, caché y CLI
└── weekly_warehouse_client_performance/
    ├── config.py                       # nombres, eventos de origen, almacenes, semanas ISO
    ├── connections.py                  # motor lector y escritor (block Secret → env → DATABASE_URL)
    ├── schema.py                       # tablas de reporting + ensure_reporting_schema()
    ├── sql/001_reporting_schema.sql    # DDL de PostgreSQL (tabla del BRIEFING tal cual)
    ├── extract.py                      # resolve_weeks(), extract_inventory_events()   (solo SELECT)
    ├── transform.py                    # transform_weekly_performance()               (pura)
    ├── load.py                         # load_weekly_performance()                    (UPSERT)
    ├── run_log.py                      # reporting.pipeline_runs
    ├── quality.py                      # pasos opcionales
    ├── queries.py                      # lecturas para la API
    └── trigger.py                      # disparo manual desde la API
services/reporting/                     # router.py y schemas.py: solo HTTP
```

**La regla**: todo lo que calcula o mueve datos es una función pura que recibe sus dependencias (motor
de base de datos, DataFrames, semanas) como argumentos. Se prueba sin Prefect y sin Supabase.
`pipeline.py` solo envuelve esas funciones con `@task` y `@flow`. `services/reporting/` solo las
llama desde HTTP.

---

## 4. Fase 1 — Flows y tasks

### El flow principal

`weekly_warehouse_client_performance_flow` (en Prefect, `weekly-warehouse-client-performance`), con
los nombres de tasks del diseño:

| Task | Etapa | Entrada → salida |
|---|---|---|
| `start_pipeline_run` | control | parámetros → marca de agua de la última corrida correcta |
| `resolve_weeks_to_process` | extracción | ahora, corte, entorno, semana, lookback, marca de agua → `list[date]` (lunes) |
| `extract_inventory_events` | **extracción** | semanas, corte, entorno → DataFrame de eventos |
| `transform_weekly_performance` | **transformación** | DataFrame de eventos, semanas → `WeeklyPerformance` (DataFrame semanal + contadores) |
| `load_weekly_performance` | **carga** | DataFrame semanal, semanas, `computed_at` → `LoadResult(rows_upserted, rows_deleted)` |
| `check_outbound_reconciliation` | opcional | DataFrame semanal, semanas → diferencias con `stock_exit` |
| `export_weekly_snapshot` | opcional | DataFrame semanal, semanas → rutas de los JSON |
| `finish_pipeline_run` | control | `run_id`, resumen → `None` |

### Extracción

Una sola consulta sobre `telemetry_events`, solo de los cuatro tipos de origen, de la ventana de las
semanas pedidas, del `environment` configurado y con `created_at <= extracted_until` (el corte fijo de
la corrida). Los campos de `tags` se extraen **en la consulta** (`tags->>'warehouse'` en PostgreSQL,
`JSON_EXTRACT` en SQLite): nunca se trae el JSONB entero.

### Transformación: los cuatro KPIs, tal como los define el BRIEFING

| Columna | Cálculo | KPI |
|---|---|---|
| `inbound_units_count` | **suma** de `quantity` de `inbound_order_created` | Volumen de entrada |
| `outbound_orders_count` | **conteo** de `outbound_order_created` | Throughput de salida |
| `stockout_events_count` | conteo de `stock_threshold_triggered` | Frecuencia de quiebre de stock |
| `discrepancy_events_count` | conteo de `inventory_discrepancy_detected` | (apoyo) |
| `discrepancy_rate` | `discrepancy_events_count / outbound_orders_count`, **0 si no hubo salidas**, 4 decimales | Tasa de discrepancia |

Antes de agrupar: validación (almacén conocido, `client_id` no vacío, cantidad numérica),
`to_datetime(utc=True)` y `week_start` = lunes UTC, y deduplicación por id de dominio
(`inbound_order_id`, `outbound_order_id`, `trigger_order_id`, `count_id`). Sin bucles: un test analiza
el código y falla si aparece un `for` o un `while`.

### Los pasos opcionales

- **`check_outbound_reconciliation`**: el control de calidad que el diseño proponía para una v1.1.
  `outbound_order_created` lo emite el navegador, así que un despacho hecho por Swagger no deja
  evento. La task compara `outbound_orders_count` con las salidas `dispatch` de `stock_exit` de la
  misma semana y devuelve las diferencias, que se guardan como aviso. **Nunca cambia una cifra.**
- **`export_weekly_snapshot`**: escribe `week_start=YYYY-MM-DD.json` por semana en
  `data/process/reporting/…` (ignorado por git), con el mismo contrato que el endpoint de KPIs.

Las dos se invocan con `return_state=True`: un test hace fallar el snapshot («disco lleno») y
comprueba que la carga se hizo, que la corrida termina `completed` y que el fallo queda en
`warnings`.

---

## 5. Fase 2 — Resiliencia

### Reintentos, justificados uno por uno

| Task | `retries` | `retry_delay_seconds` | Por qué ese número |
|---|---|---|---|
| `resolve_weeks_to_process`, `extract_inventory_events` | 3 | 10, 60, 300 | Lecturas sin efectos. Unos 6 minutos de margen cubren un corte breve o un reinicio del pooler de Supabase sin salirse de la mañana del lunes |
| `load_weekly_performance` | 2 | 30 | Es idempotente, así que reintentar es seguro; pero cada intento escribe, y si la base sigue caída al minuto es mejor fallar y avisar |
| `start_pipeline_run`, `finish_pipeline_run` | 2 | 10 | Primera y última escritura del log: unos segundos de espera antes de perder la corrida |
| `check_outbound_reconciliation` | 1 | 10 | Es un aviso: no merece retrasar la corrida |
| `transform_weekly_performance` | 0 | — | No toca servicios externos y es determinista: si falla una vez, falla siempre |
| `export_weekly_snapshot` | 0 | — | Disco local, no un servicio externo |

Cada número está justificado en un comentario encima de su `@task`.

**Solo se reintenta lo que puede arreglarse esperando.** Todas las tasks con reintentos llevan
`retry_condition_fn=retry_on_transient_errors`: se reintenta si la excepción es un `OperationalError`
de SQLAlchemy, una conexión invalidada o un timeout; un `KeyError` o un `ValueError` fallan a la
primera. Hay un test para cada caso: un corte de conexión se reintenta y la corrida termina; un
`KeyError` se ejecuta una sola vez.

### Fallos manejados explícitamente

Las tasks críticas también se invocan con `return_state=True`. `_require(state, stage)` devuelve el
resultado si todo fue bien y, si no, lanza `PipelineStageError(stage, mensaje)`. El flow la captura
una vez, **registra la corrida como `failed` con su etapa** (`start`, `extract`, `transform` o
`load`) y la relanza, así que la corrida acaba en `Failed` en Prefect y en el log. Sin
`return_state`, el flow solo sabría que «algo falló».

### Caché de la transformación

```python
@task(name="transform_weekly_performance", cache_key_fn=transform_cache_key,
      cache_expiration=timedelta(hours=1), persist_result=True)
```

- **Qué define la clave**: un SHA-256 de **todas las filas** del DataFrame de eventos (cada una con su
  `event_id`), las semanas pedidas y `TRANSFORM_VERSION`. Si la entrada es la misma, el resultado es el
  mismo, porque la transformación es pura.
- **Cuánto vale**: una hora, el margen del ticket. Cubre el caso típico: un disparo manual poco
  después de la corrida programada, o repetir el flow tras un fallo en la carga.
- **Por qué es seguro**: un solo evento tardío cambia el hash, así que la caché nunca sirve un resultado
  viejo. Cambiar la lógica obliga a subir `TRANSFORM_VERSION`.
- **Qué no se cachea, y por qué**: la extracción (tiene que volver a leer, porque busca eventos nuevos)
  y la carga (el destino es estado externo: tiene que escribirse siempre, y repetirla es inocuo).

En Supabase se ve en la segunda corrida: `transform_weekly_performance … Finished in state
Cached(type=COMPLETED)`.

---

## 6. Fase 3 — Idempotencia y log de ejecución

### La carga

Una sola transacción (`load.load_weekly_performance`):

1. `pg_advisory_xact_lock`: dos cargas del pipeline nunca se pisan.
2. `INSERT … ON CONFLICT (warehouse, client_id, week_start) DO UPDATE` con los totales recalculados.
   El `id` de una fila existente no cambia.
3. Borrado de las filas de las semanas procesadas que el cálculo ya no produce (reemplazo por semana).

### El escenario de fallo del diseño, convertido en test

`test_a_load_that_fails_midway_leaves_the_table_as_it_was_and_the_rerun_completes_it`:

1. Una corrida correcta deja un estado conocido.
2. Llega un despacho nuevo de la misma semana.
3. La siguiente corrida hace el UPSERT y **se corta la conexión** antes del commit.
4. Comprobado: la tabla está **exactamente** como en el paso 1 (ROLLBACK), y el log dice `failed`,
   `error_stage = 'load'`, con el mensaje del corte.
5. Una tercera corrida termina bien: 3 filas, sin duplicados, y el despacho nuevo contado.

### El log: `reporting.pipeline_runs`

| Campo | Tipo | Para qué |
|---|---|---|
| `run_id` | `uuid` | El id del flow run de Prefect: enlaza el log con la UI de Prefect |
| `started_at` / `finished_at` | `timestamptz` | Hora de inicio y fin; una fila `running` antigua es una corrida muerta |
| `status` | `text` | `running`, `completed` o `failed` |
| `events_extracted`, `events_discarded`, `events_deduplicated` | `integer` | Registros procesados y calidad de la entrada |
| `rows_upserted`, `rows_deleted` | `integer` | Lo que se escribió en el destino |
| `error_stage` / `error_message` | `text` | Dónde y por qué falló |
| `warnings` | `jsonb` | Fallos tolerados de los pasos opcionales y diferencias de la conciliación |
| `source_watermark` | `timestamptz` | El corte de la extracción: hace la corrida reproducible y es la marca de agua de la siguiente |
| `weeks_processed`, `parameters`, `trigger`, `triggered_by`, `code_version` | varios | Qué recalculó, con qué parámetros, quién la lanzó y con qué versión del código |

Cada escritura del log va en su propia transacción: si la carga hace ROLLBACK, el registro del fallo
sobrevive. Tres protecciones más, todas con test:

- **Índice único parcial** `(pipeline_name) where status = 'running'`: una segunda corrida simultánea
  falla al registrarse (etapa `start`) y no toca nada.
- **Corridas colgadas**: una fila `running` de hace más de una hora se marca `failed / crashed` al
  arrancar la siguiente. El hook `on_crashed` lo hace en el momento si llega a ejecutarse.
- **Marca de agua**: solo avanza con una corrida `completed`. Un evento ingerido después se recoge en
  la siguiente corrida, que recalcula su semana.

---

## 7. Fase 4 — Ejecución como script

```sh
python data/pipelines/pipeline.py                         # última semana cerrada + 1 de lookback
python data/pipelines/pipeline.py --week-start 2026-11-02 --lookback-weeks 0
python data/pipelines/pipeline.py --backfill-from 2026-09-07 --backfill-to 2026-11-02
python data/pipelines/pipeline.py --serve                 # deployment weekly-monday, lunes 06:00 UTC
```

(con el entorno virtual activado; si no, `uv run python …`).

- Ejecutado como script, Python solo añade `data/pipelines/` al path; el archivo añade la raíz del
  repo para poder importar `data.*` y `services.*`.
- Imprime el resumen JSON de la corrida. El código de salida es `0` si termina `completed` y `1` si
  falla una etapa crítica (con un mensaje de una línea en vez de un traceback).
- `--backfill-from/--backfill-to` corre el flow `backfill-weekly-warehouse-client-performance`, que
  llama al principal como **subflow** una vez por semana.
- `--serve` publica el deployment con `cron "0 6 * * 1"`: la frecuencia prevista del ciclo de
  reporting, documentada en la sección 15 de `PIPELINE_DESIGN.md`.

---

## 8. Fase 5 — Endpoints del backend

| Endpoint | Función de `data/pipelines/…` | Permisos | Respuestas |
|---|---|---|---|
| `GET /reporting/weekly-warehouse-client-performance?week_start=` | `queries.get_weekly_performance` | JWT | 200 con el contrato del BRIEFING; 404 sin datos; 422 si no es lunes; 503 si Supabase falla |
| `GET /reporting/pipeline-runs/latest` | `run_log.get_latest_run` | JWT | 200 con estado, inicio, fin, registros procesados y errores; 404 si nunca corrió |
| `POST /reporting/pipeline-runs` | `trigger.trigger_manual_run` | admin | 202; 409 si hay otra en curso; 422 por parámetros; 503 si Prefect o Supabase fallan |

Respuesta de KPIs: el contrato del BRIEFING (`week_start` y `entries` con los siete campos), más
`computed_at`:

```json
{
  "week_start": "2026-11-02",
  "computed_at": "2026-11-09T18:49:34Z",
  "entries": [
    { "warehouse": "los_angeles", "client_id": "soundwave_electronics", "inbound_units_count": 5,
      "outbound_orders_count": 1, "stockout_events_count": 0, "discrepancy_events_count": 0,
      "discrepancy_rate": 0.0 }
  ]
}
```

(Salida real de `queries.get_weekly_performance` contra el Supabase del proyecto.)

### El disparo manual no ejecuta el ETL dentro de la petición

`trigger_manual_run` valida (lunes, no futura, `lookback_weeks` entre 0 y 12, ninguna corrida en
curso) y, según `REPORTING_TRIGGER_MODE`:

- **`local`** (por defecto): entrega el flow a las `BackgroundTasks` de FastAPI, que lo ejecutan
  **después** de responder `202`. La corrida se sigue en `/latest`.
- **`deployment`**: `run_deployment(..., timeout=0)` la programa en el servidor de Prefect y devuelve
  su `flow_run_id`; la ejecuta el worker.

### Separación de módulos

`services/reporting/` es un módulo propio con prefijo `/reporting`. Un test analiza sus imports y
falla si aparece Pandas, Prefect o cualquiera de `extract`, `transform`, `load` o `quality`: la lógica
no se duplica en `services/`. `GET /telemetry/report` sigue en su router, sin cambios.

---

## 9. Problemas que aparecieron y cómo se resolvieron

### 9.1 SQLite no tiene esquemas

Los tests usan SQLite en memoria, y `reporting.weekly_warehouse_client_performance` no existe ahí. Se
resolvió con `ATTACH DATABASE ':memory:' AS reporting` en cada conexión
(`connections.attach_reporting_schema`): el mismo nombre calificado funciona en los dos motores. En
PostgreSQL el DDL lo ejecuta `sql/001_reporting_schema.sql` (con la tabla del BRIEFING tal cual); en
SQLite, las definiciones de `schema.py`.

### 9.2 `created_at` lo pone la base de datos

El corte `created_at <= extracted_until` dejaba fuera los eventos de los tests, porque se guardaban
con la hora real y el flow corría con un `as_of` fijo. Los tests guardan las filas con un `created_at`
controlado (`store(..., ingested_at=…)`), y eso permitió probar las llegadas tardías.

### 9.3 Un nombre de constraint de más de 63 caracteres

El nombre automático del `unique` de PostgreSQL superaría el límite de 63 caracteres y se truncaría.
Como el UPSERT referencia el constraint por **columnas** (`index_elements`) y no por nombre, no
afecta. En SQLAlchemy se le dio un nombre corto (`uq_wwcp_warehouse_client_week`).

### 9.4 El script no encontraba el paquete `data`

`python data/pipelines/pipeline.py` pone `data/pipelines/` en el path, no la raíz del repo. El archivo
añade la raíz antes de importar, y un test lo ejecuta como proceso nuevo para comprobarlo.

### 9.5 La imagen Docker no incluía `data/`

Ya lo detectó el diseño (hallazgo 8.3 del hito 18). Se añadió `data/pipelines/` al `Dockerfile` y a la
lista blanca del `.dockerignore`, y el servicio `backend` de compose monta `./data`.

### 9.6 Pequeños

- `Series.dt.weekday` está obsoleto en pandas 3: se usa `dt.day_of_week`.
- Instalar Prefect bajó `python-dateutil` de 4.0 a 2.9 (Prefect lo limita); toda la suite pasa con esa
  versión.
- En FastAPI 0.142, `app.routes` contiene routers incluidos sin `.path`: el test de separación de
  módulos usa los `paths` del esquema OpenAPI.
- El test que fija la lista de rutas de la API (`test_api_characterization.py`) se actualizó con las
  tres rutas nuevas.

---

## 10. Cómo se comprobó

| Comprobación | Resultado |
|---|---|
| `uv run pytest` (toda la suite) | **1056 passed** (998 anteriores + 58 nuevos) |
| `tests/reporting/test_transform.py` | 11: los cuatro KPIs con datos conocidos, tasa 0 sin salidas, un cliente por fila, semanas ISO en UTC, deduplicación, filtros de la extracción, sin bucles |
| `tests/reporting/test_pipeline_flow.py` | 4: flow completo, snapshot con el contrato, fallo opcional que no detiene la corrida, aviso de conciliación |
| `tests/reporting/test_resilience.py` | 6: reintentos declarados, reintento ante corte, sin reintento ante error no transitorio, carga que sigue fallando, caché y su clave |
| `tests/reporting/test_idempotency.py` | 10: dos corridas idénticas, carga doble, fallo a mitad y segunda corrida, reemplazo por semana, log completo, llegadas tardías, concurrencia, corridas colgadas, marca de agua |
| `tests/reporting/test_cli.py` | 5: el script como proceso nuevo, validación de argumentos, `main()` completo, backfill, código de salida 1 |
| `tests/reporting/test_reporting_endpoints.py` | 22: contrato de los tres endpoints, 401/403/404/409/422/503, flujo real `POST` → flow → `/latest` y KPIs, separación de módulos |
| `python data/pipelines/pipeline.py` contra Supabase | `Completed`: creó el esquema `reporting`, 2 eventos, 1 fila. Segunda corrida: transformación `Cached`, la misma fila con el mismo `id` |
| `telemetry_events` en Supabase | 19 filas antes y después |
| `git diff` de `services/telemetry/`, `services/routers/telemetry.py`, `event-schemas.json`, `infra/` | Vacío |
| `docker compose config` | Válido |

---

## 11. Cómo arrancarlo y probarlo

### El pipeline

```sh
uv sync                                    # instala prefect
uv run python data/pipelines/pipeline.py   # o `python …` con el entorno activado
```

En local lee los eventos del `TELEMETRY_ENVIRONMENT` de la API (`development`); para otro entorno,
`--environment production` o `REPORTING_ENVIRONMENT`.

### Los endpoints

```sh
uv run uvicorn services.api.main:app --reload --port 8000

TOKEN=...   # POST /auth/login (para el POST, con un usuario admin)
curl -s http://localhost:8000/reporting/weekly-warehouse-client-performance -H "Authorization: Bearer $TOKEN"
curl -s http://localhost:8000/reporting/pipeline-runs/latest -H "Authorization: Bearer $TOKEN"
curl -s -X POST http://localhost:8000/reporting/pipeline-runs -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" -d '{"week_start": "2026-11-02", "lookback_weeks": 0}'
```

También desde Swagger (`/docs`, sección **reporting**). Con Docker: `docker compose up --build -V`
(`-V` porque `prefect` es una dependencia nueva).

### Tests

```sh
uv run pytest tests/reporting
```

---

## 12. Decisiones discutibles (y cómo defenderlas)

| Decisión | Alternativa | Por qué así |
|---|---|---|
| Caché solo en la transformación | Cachear también la extracción | La extracción busca eventos nuevos: cachearla por parámetros escondería las llegadas tardías |
| Clave por contenido | Clave por parámetros (semanas) | Con la misma semana pueden llegar eventos nuevos; con el contenido, la caché nunca sirve un resultado viejo |
| Reintentar solo errores transitorios | Reintentar todo | Un error de datos fallaría igual tres veces y retrasaría el aviso unos 6 minutos |
| `return_state=True` también en las críticas | Dejar que la excepción se propague | Así el log dice en qué etapa falló |
| Conciliación como aviso, no como corrección | Corregir las cifras con `stock_exit` | El reporte mide la telemetría (BRIEFING); mezclar fuentes sin decidirlo con negocio cambiaría la definición del KPI |
| Modo `local` con `BackgroundTasks` | Solo `run_deployment` | Que el disparo manual funcione sin un servidor de Prefect ni un worker desplegados |
| Blocks `Secret` con alternativa por entorno | `SqlAlchemyConnector` | Sin dependencia extra; en local basta `DATABASE_URL` |
| Rol único en local | Dos roles desde ya | Los roles con contraseña se crean en Supabase al desplegar; mientras, la escritura en `telemetry_events` la impiden el código (solo `SELECT`) y su trigger de inmutabilidad |

---

## 13. Lo que queda pendiente

- **Parte 3**: dividir extracción, transformación y carga en subflows y construir el dashboard
  ejecutivo sobre `GET /reporting/weekly-warehouse-client-performance`.
- Crear en Supabase los roles `reporting_reader` y `reporting_writer` y los blocks `Secret` en
  Prefect.
- Desplegar un servidor de Prefect con worker (`REPORTING_TRIGGER_MODE=deployment`) en lugar de
  `--serve`.
- No se ha construido la imagen Docker (`docker compose config` es válido, pero no se ejecutó
  `docker compose build`).
- Las diferencias de la conciliación se guardan en el log, pero todavía nadie las recibe (correo o
  alerta).

---

## 14. Archivos creados y modificados

| Archivo | Cambio |
|---|---|
| `data/__init__.py`, `data/pipelines/__init__.py` | **Nuevos**: hacen importable `data.pipelines` |
| `data/pipelines/pipeline.py` | **Nuevo**: flows, tasks, CLI |
| `data/pipelines/weekly_warehouse_client_performance/*.py` | **Nuevos**: config, connections, schema, extract, transform, load, run_log, quality, queries, trigger |
| `data/pipelines/weekly_warehouse_client_performance/sql/001_reporting_schema.sql` | **Nuevo**: DDL del esquema `reporting` |
| `data/pipelines/PIPELINE_DESIGN.md` | Actualizado a lo implementado; secciones 15 y 16 |
| `data/pipelines/README.md`, `README.es.md` | Estado del pipeline |
| `services/reporting/__init__.py`, `router.py`, `schemas.py` | **Nuevos**: los tres endpoints |
| `services/api/main.py` | `include_router(reporting_router)` |
| `pyproject.toml`, `uv.lock`, `services/requirements.txt` | `prefect>=3` |
| `Dockerfile`, `.dockerignore`, `docker-compose.yml`, `services/Dockerfile` | `data/` en la imagen y en el contenedor |
| `.env.example` | Variables del pipeline |
| `.gitignore` | `/data/process/reporting/` (snapshots) |
| `tests/reporting/*` | **Nuevos**: 58 tests |
| `tests/test_api_characterization.py` | Las tres rutas nuevas |
| `hito_19.md` | **Nuevo**: este documento |

**Sin cambios**: `services/telemetry/` (incluido `analysis.py`), `services/routers/telemetry.py`,
`event-schemas.json`, `infra/supabase/telemetry_events.sql`.

---

## 15. Checklist de evaluación

| Criterio | Dónde se cumple |
|---|---|
| `data/pipelines/pipeline.py` con un flow y tres o más tasks | `weekly_warehouse_client_performance_flow` con 8 tasks (+ el flow de backfill) |
| `retries` > 0 con comentario que justifica el número | Comentario encima de cada `@task`; `test_database_tasks_declare_retries_and_the_transform_does_not` |
| Task opcional con `return_state=True` y el flow sigue | `check_outbound_reconciliation` y `export_weekly_snapshot`; `test_a_failing_optional_task_does_not_stop_the_run` |
| Transformación con `cache_key_fn` y `cache_expiration` | `transform_weekly_performance`; `test_the_transform_is_reused_from_cache_while_the_input_is_the_same` |
| Carga idempotente, sin duplicados | UPSERT por `unique (warehouse, client_id, week_start)`; `test_running_twice_over_the_same_data_leaves_the_table_identical` |
| ≥ 5 campos de metadata por corrida | `reporting.pipeline_runs` (19 campos); `test_each_run_records_start_end_counts_status_and_errors` |
| `python data/pipelines/pipeline.py` corre el ETL completo | Ejecutado contra Supabase; `test_the_script_runs_from_the_command_line…`, `test_main_runs_the_full_flow…` |
| Comando documentado | `PIPELINE_DESIGN.md` §15 y docstring de `pipeline.py` |
| Escribe en la tabla del BRIEFING; `telemetry_events` y `analysis.py` intactos | `reporting.weekly_warehouse_client_performance`; 19 filas antes y después; `git diff` vacío |
| Endpoint de estado de la última corrida | `GET /reporting/pipeline-runs/latest` |
| Endpoint de disparo manual que importa de `data/pipelines/` | `POST /reporting/pipeline-runs` → `trigger.trigger_manual_run` → `pipeline.weekly_warehouse_client_performance_flow` |
| Endpoint de filas de KPIs | `GET /reporting/weekly-warehouse-client-performance` |
| KPIs según «KPIs a medir» | `test_the_four_kpis_follow_the_briefing_definitions` (suma de unidades, conteo de pedidos, tasa = discrepancias / salidas) |
| Consistente con `PIPELINE_DESIGN.md` | Mismos nombres de flow, tasks, tablas y endpoints; diferencias en §16 |

---

## 16. Glosario

| Término | Significado |
|---|---|
| **Task crítica / opcional** | Si falla, la corrida se detiene / se anota un aviso y sigue |
| **State** | Estado de una task o un flow en Prefect: `Completed`, `Failed`, `Cached`, `Crashed`… |
| **`return_state=True`** | Recibir el State de la task en vez de su resultado (o su excepción) |
| **`retry_condition_fn`** | Función que decide si un fallo merece reintento |
| **Error transitorio** | Un fallo que puede desaparecer solo esperando (red, conexión, timeout) |
| **Clave de caché** | Identificador del resultado guardado: misma clave, mismo resultado |
| **`Cached`** | Estado de una task que no se ejecutó porque su resultado estaba en caché |
| **Subflow** | Un flow llamado desde otro flow (aquí, una semana del backfill) |
| **Servidor temporal** | El servidor de Prefect que se levanta solo si no hay `PREFECT_API_URL` |
| **BackgroundTasks** | Trabajo que FastAPI ejecuta después de enviar la respuesta |
| **`ATTACH DATABASE`** | Adjuntar otra base a una conexión SQLite con un nombre, como si fuera un esquema |
| **Advisory lock** | Candado de PostgreSQL que la aplicación toma por nombre |
