# Hito 20 — Pipeline de desempeño de negocio a producción: subflows, tests y dashboard

Este documento explica cómo se ha llevado a producción el pipeline del hito 19. El trabajo tiene
tres partes. El flow principal se divide en **subflows** (uno por etapa). Las tasks que calculan los
KPIs tienen **tests unitarios aislados**. Y los cuatro números del «Reporte Semanal de Desempeño por
Almacén y Cliente» se muestran en un **dashboard** del backoffice que Thomas (CEO) y Ana (Head of
Warehouse Operations) pueden leer sin ayuda. Está pensado para que alguien que no estuvo en el hito
anterior entienda qué cambió, por qué y cómo se comprobó.

Entregables:

- [data/pipelines/pipeline.py](data/pipelines/pipeline.py): el flow principal ahora solo orquesta
  tres subflows críticos y dos opcionales; la CLI de la Parte 2 sigue igual.
- [data/pipelines/weekly_warehouse_client_performance/transform.py](data/pipelines/weekly_warehouse_client_performance/transform.py):
  una función pura por KPI.
- [tests/pipelines/test_pipeline.py](tests/pipelines/test_pipeline.py): 13 tests unitarios de las
  tasks de transformación.
- [uis/backoffice/app/(protected)/reporting/](uis/backoffice/app/(protected)/reporting/reporting-client.tsx):
  el dashboard `/reporting`.
- [data/pipelines/PIPELINE_DESIGN.md](data/pipelines/PIPELINE_DESIGN.md): §10.1 (subflows), §13,
  §15.3 y la nueva §17.

Rama: `feature/business-performance-pipeline-production` (sale de
`feature/business-performance-pipeline-impl`, la del hito 19).

| Commit | Fase |
|---|---|
| `aa139fd` | Fase 1 — Refactorización en subflows |
| `3cc0362` | Fase 2 — Tests unitarios de las tasks de transformación |
| `71e8887` | Fase 3 — El CLI sigue funcionando tras el refactor |
| `0a0dbe8` | Fase 4 — Dashboard de negocio |

---

## Índice

1. [El encargo](#1-el-encargo)
2. [Conceptos básicos](#2-conceptos-básicos)
3. [Fase 1 — Subflows](#3-fase-1--subflows)
4. [Fase 2 — Tests unitarios](#4-fase-2--tests-unitarios)
5. [Fase 3 — El CLI tras el refactor](#5-fase-3--el-cli-tras-el-refactor)
6. [Fase 4 — Dashboard de negocio](#6-fase-4--dashboard-de-negocio)
7. [Actividad adicional](#7-actividad-adicional)
8. [Problemas que aparecieron y cómo se resolvieron](#8-problemas-que-aparecieron-y-cómo-se-resolvieron)
9. [Cómo se comprobó](#9-cómo-se-comprobó)
10. [Cómo arrancarlo y probarlo](#10-cómo-arrancarlo-y-probarlo)
11. [Decisiones discutibles (y cómo defenderlas)](#11-decisiones-discutibles-y-cómo-defenderlas)
12. [Lo que queda pendiente](#12-lo-que-queda-pendiente)
13. [Archivos creados y modificados](#13-archivos-creados-y-modificados)
14. [Checklist de evaluación](#14-checklist-de-evaluación)
15. [Glosario](#15-glosario)

---

## 1. El encargo

El ticket del tech lead pide cuatro cosas antes de la entrega a operaciones:

1. **Subflows**: dividir el flow principal para que cada fase sea independiente, testeable y
   reutilizable.
2. **Tests unitarios** de las tasks de transformación, para que un fallo se vea antes de producción.
3. Que `python data/pipelines/pipeline.py` **siga funcionando** como en la Parte 2.
4. **Un dashboard**: «nadie en el equipo de liderazgo va a consultar un endpoint».

Restricciones de siempre: `telemetry_events` y `services/telemetry/analysis.py` no se tocan, y los
nombres de subflows, tasks y tests siguen el vocabulario del BRIEFING y de `PIPELINE_DESIGN.md`. Un
subflow llamado `extract_data` no vale.

---

## 2. Conceptos básicos

### Subflow

En Prefect, un **subflow** es un `@flow` llamado desde otro flow. Aparece en la UI como una corrida
propia, hija de la principal, con su estado y sus tasks. Comparado con tener todas las tasks en un
solo flow:

- cada etapa se puede **ejecutar por separado** (por ejemplo, recalcular KPIs sin volver a cargar);
- el fallo queda **acotado**: si falla una task de la transformación, el subflow de transformación
  termina `Failed` y el principal sabe que la etapa fue `transform`;
- el flow principal se lee como el diagrama del diseño: extraer → calcular KPIs → cargar.

### Entradas y salidas explícitas

Un subflow solo conoce lo que recibe por argumentos y solo entrega lo que devuelve. Aquí cada uno
devuelve un tipo con nombre (`InventoryActivity`, `WeeklyPerformance`, `LoadResult`), así que se ve
exactamente qué pasa de una etapa a la siguiente.

### Test unitario aislado

Un test que comprueba **una** función con datos inventados en memoria, sin base de datos, sin red y
sin Prefect. Es rápido (2 s los 13) y, si falla, dice exactamente qué cálculo se rompió.

---

## 3. Fase 1 — Subflows

### Antes y después

En el hito 19 el flow principal llamaba directamente a cuatro tasks críticas. Ahora llama a cinco
subflows, todos con `return_state=True`:

```
weekly-warehouse-client-performance                       (flow principal: solo orquesta)
├─ start_pipeline_run                                     (log: corrida running)
├─ extract-inventory-activity                             SUBFLOW 1 · extracción
│    ├─ resolve_weeks_to_process
│    └─ extract_inventory_events                          telemetry_events (solo lectura)
├─ compute-weekly-warehouse-client-kpis                   SUBFLOW 2 · transformación
│    ├─ prepare_inventory_events                          validar, tipar, semana ISO, deduplicar
│    ├─ compute_inbound_volume                            Volumen de entrada
│    ├─ compute_outbound_throughput                       Throughput de salida
│    ├─ compute_stockout_frequency                        Frecuencia de quiebre de stock
│    ├─ compute_discrepancy_rate                          Tasa de discrepancia
│    └─ assemble_weekly_performance                       la fila del BRIEFING
├─ load-weekly-warehouse-client-performance               SUBFLOW 3 · carga
│    └─ load_weekly_performance                           UPSERT en reporting.weekly_…
├─ reconcile-outbound-throughput                          OPCIONAL
│    ├─ extract_stock_exit_dispatches                     stock_exit (otra tabla de dominio)
│    └─ compare_outbound_throughput
├─ export-weekly-performance-snapshot                     OPCIONAL
│    └─ export_weekly_snapshot
└─ finish_pipeline_run                                    (log: corrida completed)
```

### Entradas y salidas de cada subflow

| Subflow | Entradas | Salida |
|---|---|---|
| `extract_inventory_activity` | `as_of`, `extracted_until`, `environment`, `week_start`, `lookback_weeks`, `last_watermark`, `include_late_arrivals` | `InventoryActivity(weeks, events)` |
| `compute_weekly_warehouse_client_kpis` | `events`, `weeks` | `WeeklyPerformance(weekly, events_in, events_discarded, events_deduplicated)` |
| `load_weekly_warehouse_client_performance` | `weekly`, `weeks`, `computed_at` | `LoadResult(rows_upserted, rows_deleted)` |
| `reconcile_outbound_throughput` | `weekly`, `weeks` | lista de diferencias con `stock_exit` |
| `export_weekly_performance_snapshot` | `weekly`, `weeks`, `computed_at` | rutas de los JSON |

### Qué pasa cuando algo falla

- Una task falla tras sus reintentos → su subflow termina `Failed` → `_require(state, "transform")`
  (por ejemplo) registra la corrida como `failed` con esa etapa y la detiene. Es el mismo log de
  `reporting.pipeline_runs` del hito 19.
- Un subflow opcional falla → `_optional` lo anota en `warnings` y la corrida termina `Completed`.

### Una función pura por KPI

Para que cada KPI tenga su propia task, `transform.py` pasó de una función grande a seis pequeñas:
`prepare_inventory_events`, `inbound_volume`, `outbound_throughput`, `stockout_frequency`,
`discrepancy_rate` y `assemble_weekly_performance`. `transform_weekly_performance()` sigue
existiendo y las compone, así que los tests del hito 19 no cambiaron.

De paso, dos mejoras defensivas:

- Un `timestamp` ilegible se **descarta y se cuenta** (`events_discarded`). Antes hacía fallar toda
  la corrida.
- Si a una función le llega algo que no es un DataFrame, o le faltan columnas, falla con un mensaje
  claro (`inbound_volume: faltan las columnas ['quantity']`). Es un error de programación, no un
  dato a descartar.

### Caché

La caché de una hora por contenido, que en el hito 19 solo tenía `transform_weekly_performance`,
ahora la tienen **las seis tasks de transformación**. `transformation_cache_key` combina el nombre
de la task, un hash de sus entradas y `TRANSFORM_VERSION`, que pasó a `2` porque la lógica cambió.
Los reintentos no cambian.

---

## 4. Fase 2 — Tests unitarios

[tests/pipelines/test_pipeline.py](tests/pipelines/test_pipeline.py) llama a cada task por su
función (`pipeline.compute_inbound_volume.fn(...)`), sin el motor de Prefect.

**Datos de prueba con la forma de la telemetría.** `telemetry_event()` construye eventos con el Event
Envelope de `event-schemas.json` (`eventId`, `timestamp`, `event_type`, `source`, `environment`,
`properties` con `warehouse`, `client_id`, `quantity` y el id de dominio). `as_extracted()` los deja
en la forma que entrega `extract_inventory_events`.

**Aislamiento garantizado.** La fixture `no_database` (automática) sustituye los motores de base de
datos por una función que hace fallar el test. Si una transformación intentara conectarse, se vería.

**La semana conocida, calculada a mano:**

| Almacén × cliente | Eventos | Volumen | Throughput | Quiebres | Tasa |
|---|---|---|---|---|---|
| Los Ángeles × PureStep | entradas de 120 + 300 + 0 uds., 4 despachos, 1 quiebre, 1 discrepancia | 420 | 4 | 1 | 1 / 4 = 0,25 |
| Los Ángeles × GlowLab | entrada de 80 uds., 2 despachos | 80 | 2 | 0 | 0 / 2 = 0 |
| Zaragoza × PureStep | entrada de 50 uds., 1 discrepancia, sin despachos | 50 | 0 | 0 | 0 (sin salidas) |

### Los 13 tests

| Test | Qué comprueba |
|---|---|
| `test_compute_inbound_volume_sums_the_units_received_not_the_orders` | **Volumen de entrada** = suma de unidades (420), no número de órdenes (3) |
| `test_compute_outbound_throughput_counts_dispatched_orders` | **Throughput de salida** = conteo de despachos (4 y 2) |
| `test_compute_stockout_frequency_counts_each_crossing_of_the_minimum` | **Frecuencia de quiebre de stock** = 1 |
| `test_compute_discrepancy_rate_matches_the_briefing_definition` | **Tasa de discrepancia** = 1 / 4 = 0,25, según el BRIEFING |
| `test_discrepancy_rate_is_zero_when_there_were_no_outbound_orders` | 0 sin salidas (BRIEFING §4), sin división por cero |
| `test_discrepancy_rate_is_rounded_to_four_decimals` | 1 / 3 → 0,3333 |
| `test_assemble_weekly_performance_builds_the_briefing_table_for_a_known_week` | La tabla completa de la semana conocida, columna a columna |
| `test_a_row_never_mixes_clients` | Una fila por almacén × cliente × semana (BRIEFING §7) |
| `test_prepare_assigns_each_event_to_its_iso_week_in_utc` | Domingo 23:59:59.999 Z y lunes 00:00 Z caen en semanas distintas |
| `test_prepare_counts_a_movement_sent_twice_only_once` | Un despacho reenviado con otro `eventId` cuenta una vez |
| `test_prepare_discards_malformed_events_instead_of_failing` | **Defensivo**: `client_id` nulo o vacío, `quantity` "doce", nula o negativa, almacén "madrid", fecha "ayer por la tarde" o nula → 8 descartados y contados; solo cuenta el válido |
| `test_a_kpi_task_rejects_an_input_without_the_columns_it_needs` | **Defensivo**: sin `quantity` o `week_start` → `ValueError` claro; una lista en vez de un DataFrame → `TypeError` |
| `test_a_week_without_events_yields_an_empty_table_not_an_error` | Semana vacía → tabla vacía con las columnas del BRIEFING |

```
$ python -m pytest tests/pipelines/test_pipeline.py
13 passed in 1.94s
```

### Otros tests nuevos

- [tests/reporting/test_subflows.py](tests/reporting/test_subflows.py) (4 tests, con Prefect y
  SQLite en memoria):
  - cada etapa es un `@flow` con su nombre de dominio;
  - el flow principal invoca los cinco subflows con `return_state=True` y no llama a ninguna
    función de ETL directamente;
  - cada subflow se ejecuta **por separado** y su salida sirve de entrada al siguiente;
  - una task de KPI que falla detiene la corrida en la etapa `transform`.
- Jest, en el backoffice (12 tests): `__tests__/reporting.test.ts` (funciones del dashboard) y
  `__tests__/reporting-page.test.ts` (renderizado con la respuesta real de la API).

---

## 5. Fase 3 — El CLI tras el refactor

No se reconstruyó nada. El `if __name__ == "__main__"`, `main()`, las opciones (`--week-start`,
`--lookback-weeks`, `--environment`, `--backfill-from/--backfill-to`, `--serve`) y la documentación
de `PIPELINE_DESIGN.md` §15.2 siguen igual. Lo único que cambió es lo que hay debajo del flow
principal.

Ejecutado contra Supabase el 10 de noviembre de 2026, con el `python` del entorno virtual:

| Corrida | Resultado |
|---|---|
| 1.ª `python data/pipelines/pipeline.py` | Código de salida 0, `Completed`. El log muestra los cinco subflows (`extract-inventory-activity`, `compute-weekly-warehouse-client-kpis`, `load-weekly-warehouse-client-performance`, `reconcile-outbound-throughput`, `export-weekly-performance-snapshot`). Semanas `2026-10-26` y `2026-11-02`; 2 eventos; 1 fila |
| 2.ª, inmediatamente después | Las seis tasks de transformación en `Cached(type=COMPLETED)`; la tabla sigue con **una** fila |
| `telemetry_events` | 19 filas, igual que antes |

---

## 6. Fase 4 — Dashboard de negocio

`/reporting` en el backoffice, con el enlace **Reporte semanal** en la cabecera. Lo alimenta
`GET /reporting/weekly-warehouse-client-performance` (el endpoint de `services/reporting/` del hito
19), que lee `reporting.weekly_warehouse_client_performance`.

### Qué ve Thomas al abrirlo

1. **Título y explicación**: «Desempeño por almacén y cliente: cómo ha funcionado cada almacén para
   cada cliente en la semana… Se actualiza solo cada lunes por la mañana».
2. **El periodo**: «Semana del 2 al 8 de noviembre de 2026», con la fecha de actualización y botones
   «← Semana anterior» y «Semana siguiente →».
3. **Cuatro tarjetas**, una por KPI, con su nombre exacto del BRIEFING y el total de la semana:
   Volumen de entrada (unidades recibidas), Throughput de salida (pedidos despachados), Frecuencia
   de quiebre de stock (veces por debajo del mínimo) y Tasa de discrepancia (% de los pedidos de
   salida).
4. **Un panel por KPI** con lo que mide (el texto de «KPIs a medir») y una barra por almacén y
   cliente, con el valor escrito.
5. **Una tabla de detalle**, una fila por almacén y cliente, y la definición de la tasa.

### Pensado para alguien que no es ingeniero

- Nunca aparece un identificador técnico: `los_angeles × soundwave_electronics` se muestra como
  «Los Ángeles · Soundwave Electronics», y `discrepancy_rate: 0.25` como «25 %».
- La tasa total de la semana se recalcula con su definición (discrepancias / pedidos de salida de
  todas las combinaciones), no como media de las tasas de cada fila.
- Si la última semana cerrada todavía no está calculada, por ejemplo porque el lunes la corrida no
  ha terminado, un aviso lo dice en vez de mostrar datos viejos sin explicación.
- Una semana sin datos aparece como «No hay datos de esta semana», no como un error.

### Comprobación con datos reales

Con la API apuntando al Supabase del proyecto, el endpoint devolvió (HTTP 200):

```json
{"week_start":"2026-11-02","computed_at":"2026-11-10T15:57:06Z","entries":[{"warehouse":"los_angeles",
 "client_id":"soundwave_electronics","inbound_units_count":5,"outbound_orders_count":1,
 "stockout_events_count":0,"discrepancy_events_count":0,"discrepancy_rate":0.0}]}
```

Esa misma respuesta es la que usa `reporting-page.test.ts`. El test comprueba que la página muestra
el periodo, los cuatro KPIs con su nombre, «Los Ángeles · Soundwave Electronics» con 5 unidades y
«0 %», y ningún identificador técnico.

---

## 7. Actividad adicional

Es opcional, y el ticket pide no inventar mejoras para marcar la casilla. Las mejoras de resiliencia
que salieron de las preguntas de diseño ya están construidas:

- el lock de concurrencia (`pg_advisory_xact_lock` y el índice único parcial de corridas en curso);
- la marca de agua para llegadas tardías;
- la detección de corridas colgadas;
- la carga idempotente.

Lo único nuevo en esta línea es el aviso del dashboard cuando la última semana todavía no está
calculada, y nace de la Fase 4, no de una pregunta de diseño pendiente. Por eso no se añadió nada a
`PIPELINE_DESIGN.md` como actividad adicional.

---

## 8. Problemas que aparecieron y cómo se resolvieron

### 8.1 Un test de caché que dejaba de contar

`test_the_transform_is_reused_from_cache_while_the_input_is_the_same` esperaba que la primera
corrida calculara, pero la caché de Prefect se comparte en todo el módulo de tests y otro test ya
había dejado en ella exactamente la misma entrada. El test ahora usa un `TRANSFORM_VERSION` único y
comprueba el caso real: la primera corrida calcula, la segunda reutiliza y un evento nuevo obliga a
recalcular.

### 8.2 Simular la red en el test de la página

`jest.mock` con `requireActual` sobre `auth.ts` chocaba con un import circular, y `jest.spyOn` no
puede redefinir sus exportaciones. Se resolvió como en `auth.test.ts`: se simula `fetch` y se guarda
un JWT válido en `localStorage`, así que el test pasa por el `backofficeFetch` real (cabecera
`Authorization` incluida).

### 8.3 Jest solo recoge `.test.ts` y no hay `jest-dom`

El test de renderizado usa `createElement` en lugar de JSX y aserciones normales (`toBeTruthy`,
`toBeNull`). No hizo falta cambiar la configuración ni instalar dependencias.

### 8.4 `eslint` sin argumentos marca 4363 problemas

Ninguno es de este hito. Salen de `.next-lighthouse/` (artefactos de compilación antiguos) y de un
archivo de `talent/` que ya estaba así. Los archivos nuevos y el de la cabecera pasan `eslint` sin
avisos.

---

## 9. Cómo se comprobó

| Comprobación | Resultado |
|---|---|
| `python -m pytest tests/pipelines/test_pipeline.py` | **13 passed** (1,9 s) |
| `uv run pytest` (toda la suite) | **1073 passed** (1056 del hito 19 + 13 de `tests/pipelines` + 4 de `test_subflows.py`) |
| `npx jest` (backoffice) | **200 passed**, 12 de ellos nuevos |
| `npx tsc --noEmit` | Sin errores |
| `npx next build` | Compila; `/reporting` en la lista de rutas |
| `python data/pipelines/pipeline.py` contra Supabase | `Completed` con los cinco subflows; 2.ª corrida con las seis transformaciones `Cached` |
| `GET /reporting/weekly-warehouse-client-performance` contra Supabase | 200 con la semana `2026-11-02`; 404 con `week_start=2026-10-26` |
| `telemetry_events` | 19 filas antes y después |
| `git diff 9371d33 HEAD` de `services/telemetry/`, `services/routers/telemetry.py`, `event-schemas.json`, `infra/` | Vacío |

**No se comprobó en un navegador.** No he abierto `/reporting` con sesión iniciada. La página se
verificó compilándola y renderizándola en Jest con la respuesta real de la API, pero no se ha visto
con los ojos.

---

## 10. Cómo arrancarlo y probarlo

```sh
# Pipeline
python data/pipelines/pipeline.py          # o `uv run python …`

# Tests
python -m pytest tests/pipelines/test_pipeline.py
uv run pytest tests/reporting tests/pipelines
cd uis/backoffice && npx jest __tests__/reporting.test.ts __tests__/reporting-page.test.ts

# Dashboard
uv run uvicorn services.api.main:app --reload --port 8000
cd uis/backoffice && npm run dev            # http://localhost:3001/reporting (con sesión iniciada)
```

Con Docker: `docker compose up --build -V` y `http://localhost:3001/reporting`.

---

## 11. Decisiones discutibles (y cómo defenderlas)

| Decisión | Alternativa | Por qué así |
|---|---|---|
| Una task por KPI dentro del subflow de transformación | Una sola task de transformación | Cada número del BRIEFING tiene su función, su nombre en la UI de Prefect y su test; un fallo dice qué KPI se rompió |
| Caché en las seis tasks de transformación | Cachear solo una | Se mantiene el requisito del hito 19 («no repetir en la última hora») ahora que la transformación está repartida |
| Tests sobre `task.fn` | Ejecutar las tasks con Prefect | Aislamiento total y 2 s en vez de ~20 s de arranque del servidor de Prefect; lo de Prefect (reintentos, caché, subflows) ya lo prueban `tests/reporting/` |
| Datos de prueba con forma de Event Envelope | DataFrames ya extraídos | Lo pide el ticket y hace explícito que la entrada es telemetría real |
| `timestamp` ilegible: descartar | Fallar la corrida | Mismo trato que el resto de eventos malformados; queda contado en `events_discarded` |
| Columnas que faltan: fallar | Descartar | No es un dato malo sino un error de programación: tiene que verse en el test |
| Nombres de cliente generados a partir del `client_id` | Pedir los nombres a inventario | Sin una llamada extra; «Soundwave Electronics» se lee bien. Una marca con mayúsculas propias (p. ej. «GlowLab») aparece como «Glowlab» |
| Navegar semana a semana | Un selector con las semanas disponibles | El endpoint del BRIEFING ya acepta `week_start`; un listado de semanas sería un endpoint nuevo |

---

## 12. Lo que queda pendiente

- Revisar `/reporting` en un navegador con sesión iniciada (ver §9).
- Hay pocos datos reales: una sola combinación almacén × cliente en `development`. El dashboard
  lucirá cuando `production` tenga semanas completas, o tras un backfill
  (`--backfill-from … --backfill-to …`).
- Siguen pendientes los del hito 19: roles `reporting_reader` y `reporting_writer` en Supabase,
  blocks `Secret` en Prefect y un servidor de Prefect con worker (`REPORTING_TRIGGER_MODE=deployment`).
- Las diferencias de la conciliación con `stock_exit` se guardan en el log, pero todavía nadie las
  recibe.

---

## 13. Archivos creados y modificados

| Archivo | Cambio |
|---|---|
| `data/pipelines/pipeline.py` | Subflows por etapa, tasks por KPI, `transformation_cache_key`; CLI sin cambios |
| `data/pipelines/weekly_warehouse_client_performance/transform.py` | Una función pura por KPI, validación de columnas, `timestamp` ilegible descartado, `TRANSFORM_VERSION = "2"` |
| `data/pipelines/weekly_warehouse_client_performance/quality.py` | Conciliación dividida en `extract_stock_exit_dispatches` y `compare_outbound_throughput` |
| `data/pipelines/weekly_warehouse_client_performance/config.py` | Nombres de los subflows |
| `data/pipelines/PIPELINE_DESIGN.md` | §10.1, diagrama, estructura, §13, §15.3 y §17 |
| `tests/pipelines/test_pipeline.py` | **Nuevo**: 13 tests unitarios |
| `tests/reporting/test_subflows.py` | **Nuevo**: 4 tests de subflows |
| `tests/reporting/test_resilience.py`, `test_pipeline_flow.py` | Nombres de las tasks y subflows nuevos |
| `uis/backoffice/app/(protected)/reporting/page.tsx`, `reporting-client.tsx` | **Nuevos**: el dashboard |
| `uis/backoffice/app/lib/reporting.ts` | **Nuevo**: llamada al endpoint y formato |
| `uis/backoffice/app/ui/backoffice-header.tsx` | Enlace «Reporte semanal» |
| `uis/backoffice/__tests__/reporting.test.ts`, `reporting-page.test.ts` | **Nuevos**: 12 tests de Jest |
| `hito_20.md` | **Nuevo**: este documento |

**Sin cambios**: `services/telemetry/` (incluido `analysis.py`), `services/routers/telemetry.py`,
`services/reporting/`, `event-schemas.json`, `infra/`.

---

## 14. Checklist de evaluación

| Criterio | Dónde se cumple |
|---|---|
| El flow principal invoca ≥ 3 subflows en lugar de contener la lógica | 3 críticos + 2 opcionales; `test_the_main_flow_invokes_the_subflows_and_holds_no_etl_logic` |
| Cada subflow con entradas y salidas explícitas, ejecutable por separado | Tabla de §3; `test_each_subflow_runs_on_its_own_with_explicit_inputs_and_outputs` |
| Pasos opcionales como subflows con `return_state=True` | `reconcile_outbound_throughput`, `export_weekly_performance_snapshot`; `test_a_failing_optional_task_does_not_stop_the_run` |
| `tests/pipelines/test_pipeline.py` con ≥ 3 tests de tasks de transformación | 13 tests sobre las seis tasks |
| Tests aislados, en memoria, con forma de telemetría | Event Envelope en memoria; fixture `no_database` |
| ≥ 1 test defensivo ante entrada inválida | `test_prepare_discards_malformed_events_instead_of_failing`, `test_a_kpi_task_rejects_an_input_without_the_columns_it_needs` |
| ≥ 1 test que valida un KPI contra su definición | `test_compute_discrepancy_rate_matches_the_briefing_definition` (1/4), `test_compute_inbound_volume_sums_…` (420) y la tabla completa |
| `python -m pytest tests/pipelines/test_pipeline.py` pasa | 13 passed |
| `python data/pipelines/pipeline.py` sigue corriendo el ETL completo | Ejecutado contra Supabase (§5); `tests/reporting/test_cli.py` (5 passed) |
| Nombres con el vocabulario del BRIEFING | `extract_inventory_activity`, `compute_weekly_warehouse_client_kpis`, `compute_inbound_volume`, `compute_outbound_throughput`, `compute_stockout_frequency`, `compute_discrepancy_rate`, `load_weekly_warehouse_client_performance`… |
| `telemetry_events` y `analysis.py` sin modificar | 19 filas; `git diff` vacío |
| Dashboard en `uis/backoffice/` con cada KPI etiquetado, alimentado por `services/reporting/` | `/reporting` → `GET /reporting/weekly-warehouse-client-performance`; `reporting-page.test.ts` |
| Legible para un stakeholder no técnico | Nombres del BRIEFING, periodo en palabras, almacenes y clientes con nombre, porcentajes, sin identificadores técnicos |

---

## 15. Glosario

| Término | Significado |
|---|---|
| **Subflow** | Un `@flow` llamado desde otro flow; corrida propia en Prefect, hija de la principal |
| **`task.fn`** | La función original de una task, sin el motor de Prefect: lo que usan los tests unitarios |
| **Event Envelope** | La estructura común de todo evento de TrackFlow (`eventId`, `timestamp`, `event_type`, `properties`…) |
| **Test defensivo** | Comprueba qué hace el código con una entrada inválida: descartar y contar, o fallar con un mensaje claro |
| **`TRANSFORM_VERSION`** | Versión de la lógica de transformación; cambiarla invalida la caché |
| **Semana cerrada** | La semana ISO (lunes a domingo, UTC) que ya terminó: la que el pipeline publica cada lunes |
