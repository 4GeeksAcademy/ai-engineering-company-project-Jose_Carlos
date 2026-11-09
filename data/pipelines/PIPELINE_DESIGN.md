# PIPELINE_DESIGN — Desempeño semanal por almacén y cliente

> **Estado:** diseño (hito 18). Todavía no hay código de orquestación: este documento es el
> contrato que la implementación (Partes 2 y 3) tiene que cumplir.
>
> **Pipeline:** `weekly_warehouse_client_performance`
> **Entregable de negocio:** «Reporte Semanal de Desempeño por Almacén y Cliente»
> **Audiencia:** Thomas (CEO) y Ana (Head of Warehouse Operations)
> **Fuente:** `telemetry_events` (solo lectura) · **Destino:** esquema `reporting`
> **Fuente de requisitos:** BRIEFING del pipeline de desempeño de negocio de TrackFlow (entregable,
> KPIs, datos de origen, agregación, tabla de destino, endpoints y restricciones) y BRIEFING de
> telemetría (métricas obligatorias y campos mínimos de `properties`).

## Índice

1. [Estado actual](#1-estado-actual)
2. [La brecha de negocio](#2-la-brecha-de-negocio)

---

## 1. Estado actual

### 1.1 Qué eventos se capturan

La telemetría de TrackFlow se planificó en `TELEMETRY_PLAN.md` (hito 14), se instrumentó en el hito 15,
se persiste desde el hito 16 y se analiza desde el hito 17. El contrato de cada evento está en
[`event-schemas.json`](../../event-schemas.json) (allowlist de `properties`, una por tipo).

Eventos que **se emiten hoy**:

| Categoría | `event_type` | Clasificación | Origen (`source`) | Dónde se emite |
|---|---|---|---|---|
| inventory | `inbound_order_created` | **obligatoria** | `backoffice_web` | `inventoryApi.registerEntry` (`uis/backoffice/app/lib/inventory.ts`), al recibir el 201 de `POST /inventory/orders/inbound` |
| inventory | `outbound_order_created` | **obligatoria** | `backoffice_web` | `inventoryApi.registerExit`, al recibir el 201 de `POST /inventory/orders/outbound` con `exit_type = dispatch` |
| inventory | `stock_threshold_triggered` | **obligatoria** | `api` | `register_exit` (`services/inventory_service.py`), tras el commit, cuando `stock_before >= min_stock` y `stock_after < min_stock` (disparo por flanco) |
| inventory | `inventory_discrepancy_detected` | **obligatoria** | `api` | `register_count`, tras el commit, cuando `counted_quantity != system_quantity` |
| inventory | `direct_stock_edit_rejected` | **obligatoria** | `api` | `services/direct_stock_edit.py` |
| inventory | `stock_loss_recorded`, `outbound_order_rejected` | oportunidad | `backoffice_web` | formularios de salida |
| navigation | `page_viewed`, `order_form_abandoned` | oportunidad | `backoffice_web` | `TelemetryService` del backoffice |
| performance | `page_load_recorded` | oportunidad | `backoffice_web` | `TelemetryService` (Navigation Timing + LCP) |
| errors | `frontend_error_captured`, `api_request_failed` | oportunidad | `backoffice_web` | `TelemetryService` |
| authentication | `login_failed`, `session_expired` | oportunidad | `backoffice_web` | formulario de login / cliente HTTP |
| authentication | `user_logged_in` | oportunidad | `api` | `_issue_token()` (`services/api/routes/auth.py`, hito 17) |

Los cuatro eventos de inventario que usa este pipeline llevan **todos** los campos mínimos que exige
el BRIEFING de telemetría (`warehouse`, `client_id`, `product_id`, `product_category`, `quantity`) más
un identificador del registro de dominio que los originó:

| `event_type` | Campos relevantes en `properties` (schema `1.0.0`) | Id de dominio |
|---|---|---|
| `inbound_order_created` | `warehouse`, `country`, `client_id`, `product_id`, `product_category`, `quantity` (unidades recibidas), `stock_after` | `inbound_order_id` (= `stock_entry.id`) |
| `outbound_order_created` | ídem, `quantity` = unidades despachadas, `stock_after` | `outbound_order_id` (= `stock_exit.id`, `exit_type = dispatch`) |
| `stock_threshold_triggered` | ídem, `quantity` = stock tras el cruce, `min_stock`, `stock_before`, `trigger_order_type` (`dispatch`/`loss`) | `trigger_order_id` (= `stock_exit.id`) |
| `inventory_discrepancy_detected` | ídem, `quantity` = \|diferencia\|, `system_quantity`, `counted_quantity`, `difference`, `count_type` (`cycle_count`/`full_audit`) | `count_id` (= `stock_count.id`) |

Valores de dominio: `warehouse ∈ {los_angeles, zaragoza}` (mapeados desde los códigos internos `LA` /
`ZGZ` de `sku.warehouse`, `stock_entry.warehouse`…), `country ∈ {US, ES}`, `client_id` = slug
determinista de `sku.client_name` (`PureStep Footwear` → `purestep_footwear`), `product_id` = código
SKU del cliente (`sku.sku`, p. ej. `CLT-SNK-W-42`), `product_category ∈ {fashion, electronics, cosmetics}`.

> **Campos aditivos de payload:** ninguno. Todo lo que necesitan los cuatro KPIs ya está en los
> esquemas `1.0.0`, así que este diseño **no cambia** `event-schemas.json` ni la emisión.

### 1.2 Dónde se almacenan

Una sola tabla en Supabase (PostgreSQL), `public.telemetry_events`, definida en
[`services/telemetry_models.py`](../../services/telemetry_models.py) y en
[`infra/supabase/telemetry_events.sql`](../../infra/supabase/telemetry_events.sql):

| Columna | Tipo | Significado |
|---|---|---|
| `id` | `uuid` PK | `eventId` del emisor: un reintento del mismo lote no duplica filas (`ON CONFLICT DO NOTHING`) |
| `event_type` | `text` | Tipo del catálogo |
| `timestamp` | `timestamptz` | **Momento de la captura** (cuándo ocurrió el hecho) |
| `session_id`, `user_id` | `text` null | Sesión y usuario seudónimo |
| `source` | `text` | `api` \| `backoffice_web` |
| `tags` | `jsonb` | `properties` tal cual + `environment`, `schema_version`, `request_id` |
| `created_at` | `timestamptz` | **Momento de la ingesta** (lo pone la base de datos) |

Propiedades que condicionan el diseño:

- **Inmutable.** La API solo hace `INSERT`; un trigger rechaza `UPDATE`, `DELETE` y `TRUNCATE`. Un
  evento nunca cambia después de guardarse.
- **Índices** sobre `timestamp`, `event_type` y GIN sobre `tags`: una consulta por ventana de fechas
  y tipos de evento no recorre la tabla entera.
- **RLS activado sin políticas:** la API REST pública de Supabase no la lee; solo se accede por
  conexión directa a PostgreSQL.
- **`timestamp` ≠ `created_at`.** El backoffice envía en lotes (cada 10 s o 20 eventos, `sendBeacon`
  al ocultar la pestaña) y reintenta si la API responde 503: un evento del domingo a las 23:58 puede
  ingerirse el lunes, o días después si el navegador estuvo sin conexión. Es la base de la estrategia
  de llegadas tardías (sección 6).

### 1.3 Qué responde ya el reporte técnico

`GET /telemetry/report` (hito 17) llama a `services/telemetry/analysis.build_report(start, end)` y
devuelve, para una ventana `[start_date, end_date)` (por defecto los últimos 7 días, máximo 90), cinco
métricas operacionales calculadas al vuelo con Pandas y cacheadas 60 s en memoria:

| Métrica | Pregunta técnica que responde | Dimensión |
|---|---|---|
| `events_per_day` | ¿Llega telemetría de la API y del backoffice cada día? | día × `source` |
| `events_by_type` | ¿Qué tipos de evento dominan? ¿Cambió de golpe la mezcla? | día × `event_type` |
| `error_rate_by_type` | ¿Qué se está rompiendo y cuánto pesa? | día × tipo de error |
| `page_load_latency` | ¿Qué pantallas van lentas (TTFB/LCP p50 y p95)? | día × `page_route` |
| `auth_failure_rate` | ¿Cuántos intentos de login fallan? | día |

Lo consume el equipo de ingeniería en el dashboard `/telemetry` del backoffice. Responde a **«¿qué tan
sano está el sistema?»** y nada más: ninguna métrica lee `warehouse`, `client_id` ni `quantity`.

---

## 2. La brecha de negocio

El BRIEFING de la compañía describe el problema: Thomas gestiona TrackFlow con un **informe semanal
consolidado** que cada director arma a mano el domingo por la noche, con horas de trabajo y datos que
ya llegan con uno o dos días de retraso. La pregunta que ese informe intenta responder, y que **sigue
sin respuesta**, es:

> **«¿Cómo ha funcionado cada almacén para cada cliente esta semana: cuánto ha recibido, cuánto ha
> despachado, cuántas veces ha estado a punto de quedarse sin stock y cuán fiable es su inventario?»**

Contrastada KPI por KPI con lo que ya existe:

| KPI del BRIEFING | ¿Lo responde `GET /telemetry/report`? | Por qué no |
|---|---|---|
| **Volumen de entrada** | No | `events_by_type` cuenta cuántos `inbound_order_created` hubo al día en total, pero no **suma `quantity`** (unidades) ni separa por `warehouse` y `client_id` |
| **Throughput de salida** | No | El conteo existe solo como total diario del sistema; Ana necesita pedidos por almacén **y** cliente |
| **Frecuencia de quiebre de stock** | No | `stock_threshold_triggered` aparece como un tipo más en la mezcla; nadie lo atribuye al cliente dueño del SKU |
| **Tasa de discrepancia** | No | Ninguna métrica cruza dos tipos de evento de negocio en una razón (`inventory_discrepancy_detected / outbound_order_created`) por almacén y cliente |

Y aunque se añadieran esas métricas a `analysis.py`, el reporte técnico **seguiría sin servir** para
este entregable, por razones estructurales:

1. **No hay grano semanal.** Agrupa por día UTC; el liderazgo razona por semana ISO (lunes a domingo).
2. **No hay historia.** Se recalcula en cada petición sobre una ventana máxima de 90 días y no guarda
   nada: el número que Thomas vea el martes podría no coincidir con el del lunes, y no se puede
   comparar con hace seis meses.
3. **No hay trazabilidad de corrida.** Nadie puede decir «estas cifras se calcularon el lunes a las
   06:00 con los eventos ingeridos hasta las 05:59».
4. **No es para esta audiencia.** Es un endpoint técnico, con métricas de salud del sistema, y su
   contrato (`period` + `metrics`) ya lo consume el dashboard de ingeniería; cambiarlo rompería ese
   uso. El BRIEFING lo deja fuera de alcance.

Conclusión: el «Reporte Semanal de Desempeño por Almacén y Cliente» requiere un **pipeline dedicado**
que lea `telemetry_events` en solo lectura, agregue por `warehouse × client_id × week_start`, **persista**
el resultado en una tabla propia del esquema `reporting` y lo exponga por un módulo nuevo,
`services/reporting/`. `services/telemetry/analysis.py` y `GET /telemetry/report` no se tocan.
