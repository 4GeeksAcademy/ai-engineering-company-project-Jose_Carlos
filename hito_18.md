# Hito 18 — Pipeline de desempeño de negocio: fase de diseño

Este documento explica, desde cero, cómo se ha pasado de **tener telemetría que mide la salud del
sistema** (hito 17) a **tener el diseño de un pipeline que convierte esa misma telemetría en números
de negocio**: el «Reporte Semanal de Desempeño por Almacén y Cliente» que Thomas (CEO) y Ana (Head of
Warehouse Operations) hoy reciben armado a mano cada domingo por la noche. Está pensado para que
alguien que nunca ha diseñado un pipeline ETL termine sabiendo por qué el diseño tiene las piezas que
tiene, qué problema resuelve cada una y qué pasa cuando algo falla a mitad de camino.

En este hito **no hay código de orquestación**: el tech lead pidió primero el diseño y después la
implementación. El entregable formal es:

- [data/pipelines/PIPELINE_DESIGN.md](data/pipelines/PIPELINE_DESIGN.md): el documento de diseño del
  pipeline `weekly_warehouse_client_performance`.
- [data/pipelines/README.md](data/pipelines/README.md) y [README.es.md](data/pipelines/README.es.md):
  índice de pipelines de la carpeta.

Rama: `feature/business-performance-pipeline` (sale de `feature/telemetry-capture`, que contiene los
hitos 15 a 17).

Commits, uno por fase:

| Commit | Fase |
|---|---|
| `203d17c` | Fase 1 — Estado actual y brecha de negocio |
| `68bc706` | Fase 2 — Diseño del pipeline (propósito, extracción, flujo, actualizaciones, destino) |
| `222a28b` | Fase 3 — Idempotencia y log de ejecución |
| `d103688` | Fase 4 — Mapeo a Prefect |
| `562e4f6` | Fase 5 — Integración con `services/reporting/` |

---

## Índice

1. [El encargo](#1-el-encargo)
2. [Conceptos básicos](#2-conceptos-básicos)
3. [Fase 1 — Análisis del estado actual](#3-fase-1--análisis-del-estado-actual)
4. [Fase 2 — Diseño del pipeline](#4-fase-2--diseño-del-pipeline)
5. [Fase 3 — Resiliencia e idempotencia](#5-fase-3--resiliencia-e-idempotencia)
6. [Fase 4 — Mapeo a Prefect](#6-fase-4--mapeo-a-prefect)
7. [Fase 5 — Integración con la aplicación](#7-fase-5--integración-con-la-aplicación)
8. [Hallazgos que cambiaron el diseño](#8-hallazgos-que-cambiaron-el-diseño)
9. [Cómo se comprobó](#9-cómo-se-comprobó)
10. [Decisiones discutibles (y cómo defenderlas)](#10-decisiones-discutibles-y-cómo-defenderlas)
11. [Lo que queda pendiente](#11-lo-que-queda-pendiente)
12. [Archivos creados y modificados](#12-archivos-creados-y-modificados)
13. [Checklist de evaluación](#13-checklist-de-evaluación)
14. [Glosario](#14-glosario)

---

## 1. El encargo

El brief del tech lead, resumido: *«Antes de escribir una sola línea de código de orquestación,
documenta el diseño de un pipeline nuevo. No es para nosotros: es para el liderazgo, que quiere un
reporte de verdad en lugar de un PDF armado a mano.»*

Las reglas no negociables:

1. **`telemetry_events` es la fuente, nunca el destino.** El pipeline la lee en solo lectura.
2. **El reporte técnico no se toca.** `services/telemetry/analysis.py` y `GET /telemetry/report`
   siguen sirviendo a ingeniería igual que antes.
3. **El resultado vive aparte**: tablas nuevas en un esquema `reporting` y un módulo nuevo
   `services/reporting/`.
4. **Vocabulario del dominio.** Nombres de campos, ids y valores tienen que ser los de TrackFlow
   (`warehouse = los_angeles | zaragoza`, `client_id`, `inbound_order_created`…). Un diseño genérico no
   se acepta.

El BRIEFING del pipeline concreta el resto: el entregable (un consolidado **semanal, por almacén y
por cliente**), los cuatro KPIs, los cuatro eventos de origen, el grano, la tabla de destino con su
DDL exacto y los tres endpoints.

---

## 2. Conceptos básicos

### ETL: extraer, transformar, cargar

Un pipeline de datos casi siempre tiene tres etapas:

| Etapa | Pregunta | En este pipeline |
|---|---|---|
| **Extracción** | ¿Qué datos leo y de dónde? | Los cuatro tipos de evento de inventario de `telemetry_events`, solo de las semanas a procesar y solo de producción |
| **Transformación** | ¿Cómo los convierto en lo que necesito? | Validar, deduplicar, calcular el lunes de cada evento, agrupar por almacén × cliente × semana y sumar |
| **Carga** | ¿Dónde lo dejo? | En `reporting.weekly_warehouse_client_performance`, con un UPSERT dentro de una transacción |

La diferencia con el hito 17: allí se calculaba **al vuelo** en cada petición y no se guardaba nada.
Aquí se calcula **una vez por corrida** y se **persiste**: el número que Thomas ve el lunes es el
mismo que ve el jueves, y dentro de seis meses se podrá comparar.

### El grano

El **grano** es lo que representa una fila. Aquí: *un almacén, un cliente, una semana ISO* (de lunes
a domingo, en UTC). Todo el diseño se deriva de él: la clave de agrupación, el constraint `unique` de
la tabla y la clave del UPSERT son las mismas tres columnas: `warehouse`, `client_id`, `week_start`.

### Idempotencia

Una operación es **idempotente** si hacerla dos veces da el mismo resultado que hacerla una. En un
pipeline importa porque las corridas fallan y se repiten: si repetir una carga duplicara filas o
sumara dos veces, cada fallo corrompería el reporte. La idempotencia de este diseño sale de
combinar cuatro cosas: la fuente no cambia, se recalculan **totales** (no incrementos), se escribe con
UPSERT por la clave natural y la carga es una sola transacción.

### UPSERT

`INSERT … ON CONFLICT (warehouse, client_id, week_start) DO UPDATE SET …`: si la fila no existe, la
crea; si existe, la sobrescribe. Es «insertar o actualizar» en una sola sentencia atómica, y solo
funciona si hay un constraint `unique` sobre esas columnas (por eso el BRIEFING lo pone).

### Marca de agua (*watermark*)

Un evento tiene dos tiempos: `timestamp` (cuándo ocurrió) y `created_at` (cuándo llegó a la base de
datos). Un lote del navegador puede llegar horas o días tarde. La marca de agua es el `created_at`
hasta el que leyó la última corrida correcta: la siguiente busca eventos llegados después de esa
marca y recalcula las semanas a las que pertenecen. Así ningún evento tardío se pierde.

### Prefect en cinco palabras

| Concepto | Qué es |
|---|---|
| **Flow** | La función que orquesta la corrida entera |
| **Task** | Un paso dentro del flow, con sus propios reintentos y estado |
| **State** | En qué punto está una corrida o una task: `Scheduled`, `Running`, `Completed`, `Failed`, `Crashed`… |
| **Block** | Configuración guardada en Prefect, cifrada si es secreta (p. ej. la conexión a Supabase) |
| **Deployment** | Un flow publicado con su programación (cron) y sus parámetros por defecto |

---

## 3. Fase 1 — Análisis del estado actual

Secciones 1 y 2 de `PIPELINE_DESIGN.md`.

**Qué se tiene.** Se inventariaron los eventos que de verdad se emiten (no el catálogo entero) a
partir de `event-schemas.json` y del código: los cinco obligatorios de inventario y los de
oportunidad de navegación, rendimiento, errores y autenticación. Para los cuatro que usa el pipeline
se documentó el payload real: todos llevan `warehouse`, `country`, `client_id`, `product_id`,
`product_category`, `quantity` y un id de dominio (`inbound_order_id`, `outbound_order_id`,
`trigger_order_id`, `count_id`). Se describió `telemetry_events`: inmutable por trigger, con índices
por `timestamp`, `event_type` y GIN sobre `tags`, y con dos tiempos distintos (`timestamp` y
`created_at`).

**Qué responde el reporte técnico.** Las cinco métricas del hito 17: volumen por día y origen, mezcla
de tipos, tasa de errores, latencia de carga y fallos de login. Todas responden «¿qué tan sano está
el sistema?». Ninguna lee `warehouse`, `client_id` ni `quantity`.

**La brecha.** La pregunta del CEO, *«¿cómo ha funcionado cada almacén para cada cliente esta
semana?»*, no la responde ninguna métrica. Se contrastó KPI por KPI y se añadieron cuatro razones
estructurales por las que ampliar `analysis.py` tampoco serviría: no hay grano semanal, no hay
historia (se recalcula en cada petición, máximo 90 días), no hay trazabilidad de corrida y el
endpoint pertenece a otra audiencia con un contrato que ya se consume.

Una conclusión importante de esta fase: **no hace falta ningún campo de payload nuevo**. Todo lo que
piden los KPIs ya se captura desde el hito 15.

---

## 4. Fase 2 — Diseño del pipeline

Secciones 3 a 7 de `PIPELINE_DESIGN.md`.

### El propósito, en una frase

> Producir cada lunes a las 06:00 UTC, en `reporting.weekly_warehouse_client_performance`, el
> consolidado que alimenta el «Reporte Semanal de Desempeño por Almacén y Cliente» de Thomas y Ana,
> con una fila por `warehouse`, `client_id` y semana ISO que calcula Volumen de entrada, Throughput de
> salida, Frecuencia de quiebre de stock y Tasa de discrepancia a partir de `inbound_order_created`,
> `outbound_order_created`, `stock_threshold_triggered` e `inventory_discrepancy_detected`.

Va acompañada de una tabla que lleva cada columna de la tabla de destino a su KPI y a su evento. Si
una columna no se puede rastrear hasta el entregable, sobra.

Por qué el **lunes a las 06:00 UTC**: la semana cierra el domingo a medianoche UTC; seis horas dejan
llegar los lotes rezagados, y a esa hora el reporte está listo al empezar la jornada en Zaragoza y la
noche del domingo en Los Ángeles, justo cuando hoy se arma a mano.

### La extracción

Una consulta SQL que filtra en la base de datos todo lo posible (tipos de evento, ventana de fechas,
`environment = 'production'`) y proyecta solo los campos de `tags` que se usan, en lugar de traer el
JSONB entero. Incluye un corte `created_at <= :extracted_until`, fijado al principio de la corrida:
sin él, un evento ingerido mientras la corrida está a medias podría contarse en una semana y no en
otra.

### El flujo

Un diagrama Mermaid (y su versión en texto) con las tres etapas separadas, los nombres reales de las
tablas (`public.telemetry_events`, `reporting.pipeline_runs`,
`reporting.weekly_warehouse_client_performance`), las tasks y los endpoints que leen el resultado.
La transformación sigue los mismos cinco pasos que el hito 17 (cargar → refinar → convertir tipos →
agrupar → agregar), con `to_datetime(utc=True)` antes de calcular `week_start`.

### Registros que se actualizan

El enunciado pide explicar cómo tratar una fuente que **actualiza registros existentes**. En este
proyecto la respuesta tiene matices, porque `telemetry_events` **no** se actualiza nunca (un trigger
lo impide). Se identificaron los tres sitios donde sí «cambia» algo y se dio un mecanismo concreto
para cada uno:

| Qué cambia | Mecanismo |
|---|---|
| La fila semanal de destino, cuando llega un evento tardío | UPSERT por `unique (warehouse, client_id, week_start)` con totales recalculados |
| La fuente recibe hoy eventos de semanas pasadas | Marca de agua sobre `created_at` guardada en `reporting.pipeline_runs` |
| Tablas de dominio que sí se actualizan en sitio (`stock_threshold`, `sku.client_name`) | No se leen: se usa la foto del evento (`min_stock`, `client_id`) para no reescribir la historia |

### El destino

`reporting.weekly_warehouse_client_performance` con el nombre y el DDL **exactos** del BRIEFING (más
tres `check` aditivos: almacén válido, `week_start` siempre lunes, tasa no negativa) y
`reporting.pipeline_runs` para el log. Los tres endpoints de `services/reporting/` y una tabla que
los separa explícitamente de `telemetry_events` y `GET /telemetry/report`.

---

## 5. Fase 3 — Resiliencia e idempotencia

Secciones 8 y 9 de `PIPELINE_DESIGN.md`.

### Qué pasa en la segunda corrida tras un fallo en la carga

El criterio de evaluación pide describir **lo que pasa**, no lo deseable. El diseño lo hace con un
caso concreto: la corrida del lunes 16 de noviembre de 2026 pierde la conexión después de escribir 9
de 14 filas.

1. **El fallo**: PostgreSQL deshace la transacción. La tabla queda **igual que antes** de la corrida.
2. **Los reintentos**: la task de carga se repite hasta dos veces, y cada intento rehace la
   transacción entera desde el mismo DataFrame.
3. **Si no se recupera**: la corrida queda `failed` con `error_stage = 'load'`, y **la marca de agua
   no avanza**.
4. **La segunda corrida**: parte de la marca de agua de la última corrida *correcta*, así que vuelve a
   procesar las mismas semanas; lee los mismos eventos (la fuente es inmutable) más quizá alguno
   nuevo; recalcula los totales y los escribe con UPSERT. Resultado: igual que si nunca hubiera
   fallado.
5. **El caso límite**: los datos hicieron `COMMIT` pero el proceso murió antes de cerrar el log. La
   segunda corrida escribe los mismos valores; solo cambia `computed_at`.

Dos protecciones contra corridas simultáneas: un **índice único parcial** en
`reporting.pipeline_runs (pipeline_name) where status = 'running'` y un `pg_advisory_xact_lock` en la
transacción de carga (además del `concurrency_limit = 1` del deployment).

### El log de ejecución

`reporting.pipeline_runs`, con 18 campos. Cada uno con su tipo y la pregunta de auditoría que
responde. Los imprescindibles:

| Campo | Para qué sirve |
|---|---|
| `run_id` | Es el id del flow run de Prefect: enlaza el log con la UI de Prefect |
| `started_at` / `finished_at` | Duración, corridas colgadas, ¿estaba listo antes de las 07:00? |
| `status` | Lo que ve el endpoint de estado |
| `events_extracted` / `rows_upserted` | Cuadrar entrada y salida; una caída brusca delata un emisor roto |
| `error_stage` / `error_message` | Dónde y por qué falló sin abrir los logs |
| `source_watermark` | Hace la corrida reproducible y es la marca de agua de la siguiente |
| `trigger` / `triggered_by` | Por qué cambiaron unos números un miércoles, y quién lo pidió |
| `code_version` | Si cambian las cifras sin eventos nuevos, el cambio es de código |

Las escrituras del log van en **transacciones propias**: si la carga hace `ROLLBACK`, el registro del
fallo no se va con ella.

---

## 6. Fase 4 — Mapeo a Prefect

Sección 10 de `PIPELINE_DESIGN.md`.

- **Flow principal**: `weekly_warehouse_client_performance_flow` (en Prefect,
  `weekly-warehouse-client-performance`).
- **Seis tasks**: `start_pipeline_run`, `resolve_weeks_to_process`, `extract_inventory_events`
  (extracción), `transform_weekly_performance` (transformación), `load_weekly_performance` (carga) y
  `finish_pipeline_run`.
- **Reintentos por etapa, cada uno justificado**: la extracción reintenta con espera creciente
  (errores transitorios de red); la transformación **no** reintenta (es determinista: si falla una
  vez, falla siempre); la carga reintenta porque es idempotente.
- **Sin caché entre corridas**: cada corrida tiene que volver a leer la fuente, porque busca
  precisamente eventos nuevos. Tampoco se persisten los DataFrames en Prefect (llevan datos de
  clientes).
- **Estados**: tabla que relaciona `Scheduled`, `Pending`, `Running`, `Retrying`, `Completed`,
  `Failed`, `Crashed` y `Cancelled` con lo que se escribe en `reporting.pipeline_runs`, mediante los
  hooks `on_failure` y `on_crashed`.
- **Segundo flow (opcional)**: `backfill-weekly-warehouse-client-performance`, que llama al principal
  como **subflow** por semana; adelanta el patrón de la Parte 3.
- **Deployment** `weekly-monday`: `cron "0 6 * * 1"` en UTC, `concurrency_limit = 1`.
- **Blocks**: dos `SqlAlchemyConnector` con **dos roles de base de datos distintos**,
  `reporting_reader` (solo `SELECT` en `telemetry_events`) y `reporting_writer` (solo el esquema
  `reporting`). «Solo lectura» deja de ser una promesa del código y pasa a garantizarlo PostgreSQL.
  Más dos variables de Prefect (`reporting-environment`, `reporting-lookback-weeks`).

Principio que atraviesa la fase: **la lógica vive en funciones puras** (`extract.py`,
`transform.py`, `load.py`, `run_log.py`) que se prueban sin Prefect; `flow.py` solo las envuelve.

---

## 7. Fase 5 — Integración con la aplicación

Sección 11 de `PIPELINE_DESIGN.md`.

| Endpoint (`services/reporting/router.py`) | Función de `data/pipelines/weekly_warehouse_client_performance/` |
|---|---|
| `GET /reporting/weekly-warehouse-client-performance` (consulta de KPIs, feed del dashboard de la Parte 3) | `queries.get_weekly_performance(week_start)` |
| `GET /reporting/pipeline-runs/latest` (consulta de estado) | `run_log.get_latest_run(pipeline_name)` |
| `POST /reporting/pipeline-runs` (disparo manual, solo admin) | `trigger.trigger_manual_run(week_start, lookback_weeks, triggered_by)` |

Para cada uno se especificaron parámetros, respuesta de ejemplo, códigos de error y caché. El de KPIs
respeta el contrato del BRIEFING (`week_start` + `entries` con los siete campos) y añade
`computed_at`. El disparo manual **no ejecuta el ETL en la API**: programa la corrida en Prefect con
`run_deployment(..., timeout=0)` y responde `202` al instante.

La regla que lo atraviesa todo: `services/reporting/` valida, autoriza y llama a **una** función;
nunca importa `extract`, `transform`, `load` ni `flow`.

---

## 8. Hallazgos que cambiaron el diseño

### 8.1 `telemetry_events` no puede actualizarse

El enunciado pide una estrategia para una fuente que «actualiza registros existentes», pero la tabla
tiene un trigger de inmutabilidad desde el hito 16. En vez de inventar un caso que no existe, el
diseño separa lo que sí cambia (la fila de destino, las llegadas tardías y las tablas de dominio
mutables) y da un mecanismo para cada uno. Ver [Fase 2](#registros-que-se-actualizan).

### 8.2 `stock_threshold` sí es mutable

Fijar de nuevo el mínimo de un SKU sustituye la fila. Si el pipeline uniera con esa tabla, cambiar
hoy un mínimo reescribiría los quiebres de hace meses. Por eso se usa el `min_stock` que el evento
congeló en el momento del cruce, y no se lee ninguna tabla de dominio.

### 8.3 La imagen Docker no incluye `data/`

El `Dockerfile` raíz copia `services/`, `scripts/`, `packages/shared/`… pero no `data/`, y el
`.dockerignore` es una lista blanca. El servicio `api` de `docker-compose.yml` tiene `./services` como
contexto. Si `services/reporting/` importa `data.pipelines…`, en producción fallaría al arrancar. El
diseño lista los cambios necesarios (añadir `data/pipelines/` a la imagen y al compose, y
`data/__init__.py`).

### 8.4 Entradas y salidas las emite el navegador

`inbound_order_created` y `outbound_order_created` se emiten en el backoffice al recibir el `201`.
Un alta por Swagger, `curl` o `seed_inventory` no deja evento, y una pestaña cerrada antes de enviar
el lote puede perder alguno. Se documentó como riesgo, con una mitigación para una v1.1 (comparar con
`stock_exit` y registrar un aviso en el log sin tocar las cifras), sin cambiar la captura: no es objeto
de este hito.

---

## 9. Cómo se comprobó

Es un hito de diseño: no hay código nuevo que ejecutar ni tests nuevos. Lo que sí se verificó:

| Comprobación | Cómo |
|---|---|
| Los cuatro eventos traen todo lo que piden los KPIs | Lectura de `event-schemas.json` (`required` de cada `properties`, schema `1.0.0`) |
| Nombres de dominio | `warehouse`, `client_id`, ids de dominio y enums copiados del catálogo; tablas (`sku`, `stock_entry`, `stock_exit`, `stock_threshold`, `stock_count`) de `services/models.py` |
| Columnas y garantías de `telemetry_events` | `services/telemetry_models.py` e `infra/supabase/telemetry_events.sql` (inmutabilidad, índices, `created_at`) |
| Qué responde el reporte técnico | `services/telemetry/analysis.py` y `services/routers/telemetry.py` |
| Nombre y DDL de la tabla de destino | Copiados literalmente de la sección «Tabla de destino» del BRIEFING |
| Endpoints y su ruta | Sección «Nuevo endpoint de reporte» del BRIEFING; `require_admin` y `get_current_user` existen en `services/api/security.py` |
| Empaquetado | `Dockerfile`, `.dockerignore` y `docker-compose.yml` (hallazgo 8.3) |
| Fechas del ejemplo de fallo y de llegada tardía | Comprobado que `2026-10-26`, `2026-11-02`, `2026-11-09` y `2026-11-16` son lunes y `2026-11-01`, domingo |
| Que no se toca nada existente | `git diff --stat` de los cinco commits: solo `data/pipelines/` |

---

## 10. Decisiones discutibles (y cómo defenderlas)

| Decisión | Alternativa | Por qué así |
|---|---|---|
| Recalcular semanas completas | Carga incremental | El volumen semanal es de miles de eventos y así la idempotencia sale gratis |
| `lookback_weeks = 1` además de la marca de agua | Solo marca de agua | Red de seguridad que no depende de que el log esté bien |
| Sin filas de ceros | Una fila por cada SKU del catálogo | Exigiría leer `sku`, fuera de la v1; el dashboard puede pintar «sin actividad» |
| `discrepancy_rate = 0` sin salidas | `null` | Lo fija el BRIEFING; por eso `discrepancy_events_count` se expone siempre al lado |
| Dos roles de base de datos | Uno con todo | La garantía de «solo lectura» la da PostgreSQL, no la disciplina |
| Lunes 06:00 UTC | Lunes 00:00 UTC | Margen para lotes rezagados; los posteriores los recoge la marca de agua |
| `POST` con `202` y Prefect | Ejecutar el ETL en la petición | La API no se bloquea y la corrida tiene reintentos, estados y log |
| Caché de 300 s en la consulta de KPIs | Sin caché | Los datos cambian una vez por semana; `computed_at` hace visible el retraso |

Más detalle en la sección 12 de `PIPELINE_DESIGN.md`.

---

## 11. Lo que queda pendiente

- **Parte 2 — implementación**: el paquete `data/pipelines/weekly_warehouse_client_performance/`, el
  SQL del esquema `reporting`, el flow de Prefect, `services/reporting/` y los tests de la sección 13
  del diseño.
- **Parte 3**: dividir extracción, transformación y carga en subflows y construir el dashboard
  ejecutivo sobre `GET /reporting/weekly-warehouse-client-performance`.
- Crear los roles `reporting_reader` y `reporting_writer` en Supabase y los blocks en Prefect.
- v1.1: el control de calidad contra `stock_exit` (hallazgo 8.4).

---

## 12. Archivos creados y modificados

| Archivo | Cambio |
|---|---|
| `data/pipelines/PIPELINE_DESIGN.md` | **Nuevo**: documento de diseño |
| `data/pipelines/README.md`, `data/pipelines/README.es.md` | Índice de pipelines |
| `hito_18.md` | **Nuevo**: este documento |

Ningún archivo de `services/`, `uis/`, `infra/` ni `event-schemas.json` cambia en este hito.

---

## 13. Checklist de evaluación

| Criterio | Dónde se cumple (`PIPELINE_DESIGN.md`) |
|---|---|
| `data/pipelines/PIPELINE_DESIGN.md` existe y es Markdown legible | Todo el archivo, con índice |
| Sección de estado actual y brecha de negocio | §1 Estado actual, §2 La brecha de negocio |
| Formato de extracción: tablas origen, forma del payload, cadencia | §4.1, §4.2 y §4.3, §4.4 |
| Propósito en una frase con el entregable y los KPIs del BRIEFING | §3 |
| No modifica `analysis.py` ni `GET /telemetry/report`, no escribe en `telemetry_events`; destino en `reporting` y módulo `services/reporting/` | §2, §7, §10.5, §11.1 |
| Diagrama con extracción, transformación y carga y nombres reales | §5 (Mermaid + texto) |
| Mecanismo concreto para registros que se actualizan | §6.1 UPSERT, §6.2 marca de agua, §6.3 foto del evento, §6.4 reemplazo por semana |
| Idempotencia explícita: la segunda corrida tras un fallo en la carga | §8.2 |
| Log con ≥ 5 campos, nombre, tipo y justificación | §9.1 (18 campos) y §9.2 (DDL) |
| Flow principal y ≥ 3 tasks con nombres concretos | §10.1 (un flow, seis tasks) y §10.2 (backfill) |
| ≥ 3 endpoints en `services/reporting/` y la función de `data/pipelines/` de cada uno | §11.2, §11.3 |
| Consistente con los eventos y métricas obligatorias del BRIEFING | §1.1, §3, §4 (sin campos de payload nuevos) |

---

## 14. Glosario

| Término | Significado |
|---|---|
| **ETL** | *Extract, Transform, Load*: extraer, transformar y cargar |
| **Grano** | Lo que representa una fila: aquí, almacén × cliente × semana |
| **Semana ISO** | De lunes a domingo; `week_start` es su lunes, en UTC |
| **Idempotente** | Repetirlo da el mismo resultado que hacerlo una vez |
| **UPSERT** | Insertar o, si ya existe por la clave, actualizar |
| **Clave natural** | La que identifica la fila por su significado (`warehouse, client_id, week_start`), no por un id artificial |
| **Marca de agua** | Hasta qué `created_at` leyó la última corrida correcta |
| **Llegada tardía** | Evento que se ingiere después de que su semana ya se procesó |
| **Backfill** | Recalcular un rango histórico de semanas |
| **Advisory lock** | Candado de PostgreSQL que la aplicación toma por nombre; el `xact` se libera al terminar la transacción |
| **Índice único parcial** | `unique` que solo aplica a las filas que cumplen un `where` (aquí, `status = 'running'`) |
| **Flow / Task / State / Block / Deployment** | Ver [Prefect en cinco palabras](#prefect-en-cinco-palabras) |
| **Subflow** | Un flow llamado desde otro flow |
