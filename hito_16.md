# Hito 16 — Telemetría: almacenamiento en Supabase

Este documento explica, desde cero, cómo se ha pasado del **stub** de telemetría del Hito 15 a una
**ingesta real** que guarda cada evento en una tabla de Supabase. Está pensado para que alguien que
nunca ha diseñado una tabla de eventos termine sabiendo elegir sus columnas e índices, validar un lote
evento a evento sin tumbarlo entero, insertarlo de una sola vez y comprobar en la base de datos que lo
que salió del navegador es lo que quedó guardado.

Los entregables formales son:

- [services/telemetry_models.py](services/telemetry_models.py): la tabla `telemetry_events` (ocho
  columnas, tres índices) como modelo SQLModel.
- [infra/supabase/telemetry_events.sql](infra/supabase/telemetry_events.sql): el mismo DDL para el
  SQL Editor de Supabase, con RLS y el trigger de inmutabilidad.
- [services/routers/telemetry.py](services/routers/telemetry.py): `POST /telemetry/events`, ya sin
  stub. Responde `{"received", "stored", "rejected"}`.
- [services/telemetry.py](services/telemetry.py): validación por evento (`accept_events`), mapeo a
  fila (`event_row`) e inserción por lotes (`record_events`). El modelo `TelemetryEvent` **no cambia**.
- La verificación end-to-end contra Supabase: [tests/ui/telemetry.mjs](tests/ui/telemetry.mjs) con
  `TELEMETRY_E2E_SUPABASE=1` y el script de curl
  [scripts/telemetry_mixed_batch.sh](scripts/telemetry_mixed_batch.sh).
- [TELEMETRY_PLAN.md](TELEMETRY_PLAN.md), actualizado: PR-5 cerrado y nueva sección 10.1.

El frontend **no cambia ni una línea**: `git diff f5fbe07 -- uis/` está vacío.

---

## Índice

1. [El encargo](#1-el-encargo)
2. [Conceptos básicos](#2-conceptos-básicos)
3. [Fase 1 — La tabla `telemetry_events`](#3-fase-1--la-tabla-telemetry_events)
4. [Fase 2 — El endpoint real](#4-fase-2--el-endpoint-real)
5. [Fase 3 — Verificación end-to-end](#5-fase-3--verificación-end-to-end)
6. [Por qué el frontend no tuvo que cambiar](#6-por-qué-el-frontend-no-tuvo-que-cambiar)
7. [Problemas que aparecieron y cómo se resolvieron](#7-problemas-que-aparecieron-y-cómo-se-resolvieron)
8. [Cómo se comprobó](#8-cómo-se-comprobó)
9. [Cómo repetirlo y verlo en Supabase](#9-cómo-repetirlo-y-verlo-en-supabase)
10. [Decisiones discutibles (y cómo defenderlas)](#10-decisiones-discutibles-y-cómo-defenderlas)
11. [Lo que queda pendiente](#11-lo-que-queda-pendiente)
12. [Archivos creados y modificados](#12-archivos-creados-y-modificados)
13. [Lo que deberías poder explicar después de leer esto](#13-lo-que-deberías-poder-explicar-después-de-leer-esto)
14. [Glosario](#14-glosario)

---

## 1. El encargo

Tercer proyecto de la serie **Plan → Captura → Almacenamiento → Reporte**. El mensaje del tech lead
lo resumía así: *"El stub ya cumplió su función — sé que los eventos llegan con el formato correcto.
Ahora necesito que los guardes."* Y añadía una condición: *"Si el frontend necesita cambiar algo para
que esto funcione, el diseño está mal."*

El orden era obligatorio: primero la tabla en Supabase, después el endpoint real y, por último, la
verificación end-to-end.

1. **Tabla de almacenamiento en Supabase**
   - Crear `telemetry_events` con ocho columnas.
   - Mapear cada `TelemetryEvent` de la API a una fila con un contrato fijo.
   - Tres índices: `timestamp`, `event_type` y un **GIN sobre `tags`** para buscar dentro del JSONB.
   - Sin lógica de `UPDATE` ni `DELETE`: los eventos son inmutables.
2. **Endpoint real en FastAPI**
   - Mismo envelope que el stub: `{"events": [...]}`, parseado **de forma laxa**. No se puede declarar
     `events: list[TelemetryEvent]` como tipo del cuerpo.
   - Validar cada evento con `TelemetryEvent.model_validate(...)`: el mismo modelo, sin modificarlo.
   - Rechazar individualmente los inválidos **sin cancelar el lote**.
   - Insertar los válidos con **un único bulk insert**.
   - Devolver `{"received": N, "stored": M, "rejected": R}`.
   - Que la respuesta sea compatible con el `TelemetryService`, que solo mira el código HTTP.
3. **Verificación end-to-end**
   - Usar el backoffice para registrar al menos una entrada y una salida, y provocar un evento técnico.
   - Consultar la tabla y confirmar `event_type`, `timestamp` y `tags`.
   - Enviar a mano un lote mixto y comprobar `stored` y `rejected`.

**La estructura de la tabla.** La captura del enunciado no mostraba las dos tablas de columnas y
mapeo, y tampoco estaban en el BRIEFING (`CONTEXT-11`). Se propuso una estructura de ocho columnas
y se aprobó antes de empezar (sección 3).

---

## 2. Conceptos básicos

### Una tabla de eventos no es una tabla de negocio

Las tablas de inventario (`sku`, `stock_entry`…) describen el **estado** del almacén y tienen
relaciones entre ellas. Una tabla de eventos es un **registro de hechos**: cada fila dice "esto pasó
en este momento" y nunca se corrige. Por eso:

- **Solo se inserta.** Si un evento estaba mal, se emite otro que lo corrija; no se reescribe el pasado.
- **Unas pocas columnas fijas y un JSON flexible.** Las columnas son lo que tienen *todos* los eventos
  (tipo, momento, sesión, usuario, origen). Lo que cambia según el evento (almacén, SKU, ruta, motivo
  del error) va en un JSON. Así un evento nuevo del catálogo no exige migrar la tabla.

### JSONB y el índice GIN

PostgreSQL tiene dos tipos para JSON: `json` guarda el texto tal cual y `jsonb` lo guarda ya
descompuesto en binario. `jsonb` permite **indexar el contenido**. Un índice **GIN** (*Generalized
Inverted Index*) apunta de cada clave y valor a las filas que lo contienen, como el índice de un libro.
Con él, esta consulta no recorre toda la tabla:

```sql
select * from telemetry_events where tags @> '{"warehouse": "zaragoza"}';
```

`@>` significa "contiene": las filas cuyo `tags` incluye ese par clave-valor.

### Validación del lote frente a validación por evento

Si el cuerpo del endpoint se declara como `list[TelemetryEvent]`, FastAPI valida **todo el lote antes
de llamar a tu función**. Basta un evento con un campo mal para que devuelva **422** al lote entero.
El `TelemetryService` no reintenta los 4xx, así que tiraría también los eventos buenos.

| Enfoque | Qué pasa con un lote mixto |
|---|---|
| Cuerpo tipado (`events: list[TelemetryEvent]`) | Todo el request falla con 422 y no se guarda nada |
| Validación por evento (`model_validate` en un bucle) | Los válidos se guardan y los inválidos se cuentan en `rejected` |

### Bulk insert

Insertar 20 eventos con 20 sentencias `INSERT` son 20 viajes a Supabase. Un **bulk insert** los
manda en uno:

```sql
INSERT INTO telemetry_events (id, event_type, …) VALUES (…), (…), (…) …
```

Además, si el lote falla a mitad, o entra entero o no entra nada.

### Idempotencia

Una operación es **idempotente** si repetirla no cambia el resultado. Al backoffice le puede pasar
que un lote llegue a guardarse y la respuesta se pierda: lo reintentará. Si la clave primaria es el
`eventId` y el insert dice `ON CONFLICT (id) DO NOTHING`, el reintento no crea filas duplicadas.

### Trigger

Un **trigger** es una función que PostgreSQL ejecuta sola antes o después de una operación sobre una
tabla. Aquí se usa para que un `UPDATE`, `DELETE` o `TRUNCATE` sobre `telemetry_events` falle siempre,
lo lance quien lo lance.

---

## 3. Fase 1 — La tabla `telemetry_events`

### Las ocho columnas

| Columna | Tipo | Nulo | Viene de | Por qué |
|---|---|---|---|---|
| `id` | `uuid` PK | no | `eventId` | Clave de idempotencia: un reintento no duplica |
| `event_type` | `text` | no | `event_type` | El filtro más habitual; tiene índice |
| `timestamp` | `timestamptz` | no | `timestamp` | Momento de la **captura**; tiene índice para rangos de fechas |
| `session_id` | `text` | sí | `sessionId` | Agrupa el recorrido de una sesión del backoffice |
| `user_id` | `text` | sí | `userId` | Seudónimo del usuario de TinyDB; `null` antes del login |
| `source` | `text` | no | `source` | `api` o `backoffice_web` (con `CHECK`) |
| `tags` | `jsonb` | no | `properties` + 3 campos | Las dimensiones del evento; índice GIN |
| `created_at` | `timestamptz` | no | `DEFAULT now()` | Momento de la **ingesta**, lo pone la base |

`timestamp` y `created_at` no son lo mismo. Un evento capturado a las 10:00:00 puede llegar a las
10:00:10 por el debounce del lote, o mucho después si la pestaña estaba sin red. Los informes usan
`timestamp`; `created_at` sirve para medir ese retraso.

### El contrato de mapeo: `TelemetryEvent` → fila

Lo hace una sola función, `event_row()` en `services/telemetry.py`:

```python
{
    "id": uuid.UUID(event.eventId),
    "event_type": event.event_type,
    "timestamp": datetime.fromisoformat(event.timestamp),
    "session_id": event.sessionId,
    "user_id": event.userId,
    "source": event.source,
    "tags": {
        **event.properties,                       # tal cual: ya cumplen su allowlist
        "environment": event.environment,
        "schema_version": event.schemaVersion,
        "request_id": event.requestId,
    },
}
```

Los tres campos del envelope que no tienen columna propia (`environment`, `schemaVersion`,
`requestId`) van dentro de `tags`, en `snake_case`. Un test comprueba que ningún evento del catálogo
usa esos nombres en sus `properties`, así que no se pueden pisar.

### Las dimensiones del BRIEFING se conservan

El BRIEFING pide que los eventos de inventario lleven `warehouse`, `client_id`, `product_id`,
`product_category` y `quantity`, y que se puedan **agregar por almacén, por cliente y por país**. El
plan añadió `country`. Como `tags` son las `properties` **sin transformar**, esas claves llegan a la
tabla con el mismo nombre y valor que en el plan. Esta es una fila real de Supabase:

```json
{"warehouse": "los_angeles", "country": "US", "client_id": "soundwave_electronics",
 "product_id": "E2E-TEL-MW5CN26S", "product_category": "electronics", "quantity": 5,
 "inbound_order_id": 11904, "stock_after": 25,
 "environment": "development", "schema_version": "1.0.0", "request_id": "f8c27745-…"}
```

El allowlist también se conserva: un evento con una clave fuera de su esquema **no se guarda**
(sección 4). Así nada que no esté en `event-schemas.json` puede llegar a la tabla.

### Los tres índices

```sql
CREATE INDEX ix_telemetry_events_timestamp  ON telemetry_events (timestamp);
CREATE INDEX ix_telemetry_events_event_type ON telemetry_events (event_type);
CREATE INDEX ix_telemetry_events_tags       ON telemetry_events USING gin (tags);
```

| Índice | Consulta que acelera |
|---|---|
| `timestamp` | "Eventos de la última semana", series temporales del dashboard de Ana |
| `event_type` | "Todas las salidas", "todos los errores del frontend" |
| GIN `tags` | "Todo lo de Zaragoza", "todo lo del cliente GlowLab", "todo lo del SKU X" |

En el modelo, el GIN se declara con `postgresql_using="gin"`. En SQLite, que usan los tests, esa
opción se ignora y queda un índice normal.

### Inmutable: tres capas

1. **El código.** `services/telemetry.py` solo tiene un `INSERT`. Un test busca `update(`, `delete(`,
   `session.delete` o `UPDATE telemetry_events` en los tres archivos de telemetría y falla si aparecen.
2. **La base de datos.** Un trigger rechaza `UPDATE` y `DELETE` (por fila) y `TRUNCATE` (por sentencia)
   con el error `telemetry_events es inmutable: UPDATE no está permitido`. Vale también para el
   propietario de la tabla y para el SQL Editor de Supabase.
3. **La API REST de Supabase.** RLS activado y sin políticas, igual que en las tablas de inventario:
   la clave pública de Supabase no puede leer ni escribir la tabla.

Comprobado en Supabase:

```
BLOCKED UPDATE   -> InsufficientPrivilege telemetry_events es inmutable: UPDATE no está permitido
BLOCKED DELETE   -> InsufficientPrivilege telemetry_events es inmutable: DELETE no está permitido
BLOCKED TRUNCATE -> InsufficientPrivilege telemetry_events es inmutable: TRUNCATE no está permitido
```

### Cómo se crea

La API la crea sola al arrancar: `create_db_and_tables()` en `services/database.py` llama a
`SQLModel.metadata.create_all()` y después aplica el RLS y el trigger
(`telemetry_immutability_statements`). Las sentencias son idempotentes (`CREATE OR REPLACE FUNCTION`,
`DROP TRIGGER IF EXISTS` + `CREATE TRIGGER`), así que se pueden ejecutar en cada arranque.

Para crearla a mano, `infra/supabase/telemetry_events.sql` tiene el mismo DDL con `IF NOT EXISTS`. Un
test comprueba que las columnas e índices del script coinciden con los del modelo, para que no se
desincronicen.

---

## 4. Fase 2 — El endpoint real

### El recorrido de un lote

`services/routers/telemetry.py` → `services/telemetry.py`:

1. Lee el cuerpo **en crudo**: el beacon llega como `text/plain`, igual que en el hito 15. Si pasa de
   256 KB, responde **413**.
2. `TelemetryEnvelope.model_validate_json(raw)`. El envelope es **laxo**: `events: list[Any]`, de hasta
   100 elementos. Solo se comprueba que haya una lista, no lo que lleva dentro. Si no es JSON, no tiene
   `events` o tiene más de 100, responde **422** (es el único 422 posible).
3. `ingest_batch(events)` se ejecuta en el threadpool (`run_in_threadpool`), porque la escritura en
   Supabase es síncrona y no debe bloquear el bucle de eventos de FastAPI.
4. `accept_events(raw_events)` recorre el lote:
   ```python
   for index, raw in enumerate(raw_events):
       try:
           event = TelemetryEvent.model_validate(raw)       # 1) el envelope
       except ValidationError as error:
           rejected += 1; log(...); continue
       if schema_violations(event.model_dump()):           # 2) su allowlist
           rejected += 1; log(...); continue
       valid.append(event)
   ```
   Un evento que no es un objeto (por ejemplo, un string) también cae en el `except`. El bucle
   **sigue** tras cada rechazo.
5. `record_events(valid)` hace **una sola sentencia** para todo el lote:
   ```sql
   INSERT INTO telemetry_events (id, event_type, timestamp, session_id, user_id, source, tags)
   VALUES (…), (…), …
   ON CONFLICT (id) DO NOTHING
   RETURNING id
   ```
   `RETURNING id` devuelve solo las filas que se han insertado de verdad, así que `stored` no cuenta
   los duplicados.
6. Responde `200 {"received": N, "stored": M, "rejected": R}`.

### Qué se rechaza y por qué

| Caso | Ejemplo | Resultado |
|---|---|---|
| Envelope roto | `eventId` que no es UUID, `source: "mobile_app"`, falta `timestamp`, clave de más | `rejected` |
| Fuera del allowlist | `page_viewed` con un `email` en `properties` | `rejected` |
| Evento desconocido | `event_type: "order_teleported"` | `rejected` |
| No es un objeto | `"page_viewed"` | `rejected` |
| Repetido | El mismo `eventId` en un reintento | Ni `stored` ni `rejected`: ya estaba |
| Envelope ilegible | `not json`, `[]`, `{"evnts": …}`, más de 100 eventos | **422** para todo el lote |
| Supabase caído | Error de conexión | **503**: el backoffice reintenta |

Rechazar lo que se sale del allowlist es una decisión de privacidad. En el hito 15 el stub solo lo
avisaba en el log. Ahora que hay tabla, guardarlo metería justo el dato que no debía salir.

### El log: qué falla, nunca con qué valor

```
WARNING: telemetry_event_rejected index=1 reason=envelope fields=eventId
WARNING: telemetry_schema_violation index=2 event_type=page_viewed fields=properties
INFO:    telemetry stored=2 of=2 source=backoffice_web event_types=page_viewed,page_viewed
INFO:    telemetry batch received=4 stored=2 rejected=2
```

Se registra la posición y el campo, nunca el valor: si el problema es un email que se coló, el log no
debe repetirlo. Un test lo comprueba.

### `TelemetryEvent` no se ha tocado

El modelo se usa ahora **como validador de cada elemento**, no como tipo del cuerpo. Lo único que se
ha sustituido es `TelemetryBatch` (el cuerpo tipado del stub) por `TelemetryEnvelope` (el cuerpo
laxo). Se comprobó comparando el bloque de la clase con el commit del hito 15: es idéntico.

### Los eventos de la API también se guardan

`emit()` (los eventos que solo ve el servidor: `stock_threshold_triggered`,
`inventory_discrepancy_detected`, `direct_stock_edit_rejected`) ya llamaba a `record_events`. Ahora
esa función abre su propia sesión (`open_session()`) y guarda el evento. Si Supabase falla, `emit`
captura la excepción: **la telemetría nunca rompe una salida de stock**.

---

## 5. Fase 3 — Verificación end-to-end

### El recorrido en el navegador, contra Supabase

`TELEMETRY_E2E_SUPABASE=1 node tests/ui/run.mjs telemetry` arranca la API con el `DATABASE_URL` del
`.env` (Supabase) y el backoffice con `NEXT_PUBLIC_TELEMETRY_ENDPOINT` apuntando a ella. Después
recorre en Chrome el mismo flujo del hito 15:

1. Login fallido (evento técnico `login_failed`) y login correcto.
2. **Una entrada** de 5 unidades (`inbound_order_created`).
3. Una salida rechazada por stock (`outbound_order_rejected`) y **una salida** de 3 unidades
   (`outbound_order_created`).
4. Un formulario abandonado (`order_form_abandoned`).
5. Un error de JavaScript (técnico: `frontend_error_captured`).
6. Un `PUT` a `/inventory/products/{id}` para fijar stock (técnico, lo emite la API:
   `direct_stock_edit_rejected`).
7. Cerrar la pestaña (beacon).

Para no chocar con datos anteriores, cada ejecución crea un SKU de prueba con código único
`E2E-TEL-…`.

Después consulta la tabla y comprueba:

| Check | Qué verifica |
|---|---|
| TEL-14 | Cada evento enviado por el navegador está en `telemetry_events` **exactamente una vez** |
| TEL-15 | Cada fila tiene el `event_type`, el `timestamp` (al milisegundo), la sesión, el usuario y los `tags` de su evento |
| TEL-16 | La entrada y la salida conservan `warehouse`, `country`, `client_id`, `product_id`, `product_category` y `quantity` |
| TEL-17 | Los técnicos también: `login_failed`, `frontend_error_captured`, `page_load_recorded` y el `direct_stock_edit_rejected` de la API |

### Lo que quedó en Supabase

Consulta directa tras la ejecución:

```
event_type                   source           filas
direct_stock_edit_rejected   api              1
frontend_error_captured      backoffice_web   1
inbound_order_created        backoffice_web   1
login_failed                 backoffice_web   1
order_form_abandoned         backoffice_web   1
outbound_order_created       backoffice_web   1
outbound_order_rejected      backoffice_web   1
page_load_recorded           backoffice_web   3
page_viewed                  backoffice_web   7   (5 del recorrido + 2 del lote mixto)
```

Algunas filas:

| `event_type` | `timestamp` | `source` | `tags` (resumen) |
|---|---|---|---|
| `inbound_order_created` | 2026-11-06 19:10:23.844+00 | `backoffice_web` | `los_angeles`, `US`, `soundwave_electronics`, `quantity: 5`, `stock_after: 25` |
| `outbound_order_created` | 2026-11-06 19:10:26.646+00 | `backoffice_web` | `los_angeles`, `US`, `quantity: 3`, `stock_after: 22` |
| `login_failed` | 2026-11-06 19:10:21.437+00 | `backoffice_web` | `failure_reason: invalid_credentials`, `schema_version: 2.0.0`; `user_id` nulo |
| `frontend_error_captured` | 2026-11-06 19:10:27.144+00 | `backoffice_web` | `error_name: TypeError`, `error_fingerprint`, sin el mensaje |
| `direct_stock_edit_rejected` | 2026-11-06 19:10:27.702+00 | `api` | `http_method: PUT`, `rejection_type: method_not_allowed`, dimensiones del SKU |

El índice GIN se usa para buscar dentro de `tags`. Con tan pocas filas PostgreSQL prefiere leer la
tabla entera, así que se forzó con `SET enable_seqscan = off` para ver el plan:

```
Bitmap Heap Scan on telemetry_events
  Recheck Cond: (tags @> '{"warehouse": "los_angeles"}'::jsonb)
  ->  Bitmap Index Scan on ix_telemetry_events_tags
```

### El rechazo, probado a mano

`scripts/telemetry_mixed_batch.sh` manda con curl un lote de 4 eventos: 2 válidos, 1 con el `eventId`
roto y 1 con un `email` en `properties`. Contra la API conectada a Supabase:

```
POST http://127.0.0.1:8766/telemetry/events (4 eventos: 2 válidos, 1 envelope roto, 1 fuera de su allowlist)
{"received":4,"stored":2,"rejected":2}
HTTP 200
```

En la tabla aparecen los dos `eventId` válidos, y `select count(*) from telemetry_events where tags ?
'email'` devuelve **0**. La suite de Chrome repite la prueba en TEL-13 (respuesta) y TEL-18 (solo los
válidos en la tabla).

---

## 6. Por qué el frontend no tuvo que cambiar

El tech lead lo planteó como prueba del diseño, y se cumple por tres razones:

1. **Misma URL y mismo envelope.** `NEXT_PUBLIC_TELEMETRY_ENDPOINT` sigue siendo
   `http://localhost:8000/telemetry/events` y el cuerpo sigue siendo `{"events": [...]}`.
2. **El `TelemetryService` solo mira el código de estado.** Reintenta si es `>= 500` o `429` y, si no,
   da el lote por entregado. Nunca lee el cuerpo, así que pasar de `{"received"}` a
   `{"received", "stored", "rejected"}` le es indiferente. Un test nuevo lo fija: si alguien añade
   `response.json()` al servicio, falla.
3. **Los códigos significan lo mismo para él.** Un lote mixto devuelve **200**, no 422, así que no se
   descartan los válidos. Un fallo de Supabase devuelve **503**, que sí se reintenta, y el reintento no
   duplica filas gracias al `ON CONFLICT`.

El hito 15 ya lo había preparado: el stub tenía un único punto de entrada (`record_events`) y el
contrato HTTP no prometía nada que el almacenamiento tuviera que romper.

---

## 7. Problemas que aparecieron y cómo se resolvieron

### 7.1 La estructura de la tabla no estaba en el enunciado

Las capturas del checklist cortaban justo las dos tablas ("con la siguiente estructura" y "con este
contrato"), y el BRIEFING no habla de almacenamiento. Se propuso la estructura de la sección 3, que
cuenta ocho columnas (como pedía la evaluación), y se aprobó antes de escribir código.

### 7.2 Supabase no respondía

Durante las fases 1 y 2, el pooler devolvía `FATAL: (ENOTFOUND) tenant/user postgres.… not found`
con cualquier host (`aws-0`/`aws-1`) y puerto (6543/5432). Es lo que responde Supavisor cuando el
proyecto está pausado. Se siguió trabajando con SQLite, que cubre todos los tests, y la verificación
en Supabase se hizo cuando el proyecto volvió a estar disponible.

### 7.3 Un `%` en el trigger

PL/pgSQL formatea los mensajes de `RAISE` con `%`, pero psycopg, a través de SQLAlchemy, puede tomar
un `%` suelto por un parámetro. El mensaje se construye concatenando
(`'… ' || TG_OP || ' no está permitido'`) y un test comprueba que no queda ningún `%`. El primer
intento falló precisamente porque el **comentario** que lo explicaba llevaba un `%`.

### 7.4 Los eventos de la API necesitaban una base de datos en los tests

`emit()` guarda con su propia sesión, contra `database.engine`. En los tests ese motor es un
`sqlite://` sin tablas. La solución fue una fixture `autouse` (`telemetry_store` en
`tests/conftest.py`) que sustituye `telemetry.open_session` por un SQLite en memoria con la tabla
creada. Como todo pasa por esa función, una sola sustitución cubre el endpoint y `emit`.

### 7.5 Contar `stored` sin contar duplicados

`rowcount` no es fiable con `ON CONFLICT DO NOTHING` en todos los drivers. `RETURNING id` devuelve
exactamente las filas nuevas y funciona igual en PostgreSQL y en SQLite (3.35 o posterior).

### 7.6 Un fallo intermitente en la suite de Chrome

La primera ejecución de la suite modificada abortó con `TypeError: Illegal invocation` en un
`setValue`: el elemento aún no existía. Esa ejecución tardó 181 s, frente a los 22 s habituales,
porque `next dev` estaba compilando en frío. Al repetirla, con la caché ya caliente, pasó 20/20, y
también pasa contra Supabase. No se cambió nada.

### 7.7 Las comparaciones de `tags`

`jsonb` no conserva el orden de las claves. La suite compara los `tags` con las `properties` enviadas
después de ordenar las claves a cualquier profundidad.

---

## 8. Cómo se comprobó

| Comprobación | Resultado |
|---|---|
| `uv run pytest` (suite completa) | **963 / 963** |
| `tests/telemetry/test_telemetry_storage.py`: estructura, índices, mapeo e inmutabilidad (**nuevo**) | 15 / 15 |
| `tests/telemetry/test_telemetry_endpoint.py`: ingesta real (reescrito) | 48 / 48 |
| `tests/telemetry/test_frontend_contract.py`: el servicio solo lee el código HTTP | 7 / 7 |
| `tests/inventory/test_inventory_architecture.py`: RLS y tablas | 38 / 38 |
| `tests/inventory/test_inventory_telemetry.py`: eventos de la API, ahora guardados | 18 / 18 |
| `node tests/ui/run.mjs telemetry` (Chrome real, SQLite) | **20 / 20** |
| `TELEMETRY_E2E_SUPABASE=1 node tests/ui/run.mjs telemetry` (Chrome real, **Supabase**) | **20 / 20** |
| `scripts/telemetry_mixed_batch.sh` contra la API con Supabase | `{"received":4,"stored":2,"rejected":2}`, HTTP 200 |
| Estructura en Supabase (`information_schema`, `pg_indexes`, `pg_trigger`) | 8 columnas, 3 índices + PK, 2 triggers, RLS activo |
| `UPDATE` / `DELETE` / `TRUNCATE` en Supabase | Los tres rechazados por el trigger |
| `git diff f5fbe07 -- uis/` | Vacío: el frontend no cambió |
| Clase `TelemetryEvent` frente al hito 15 | Idéntica |

Algunos tests nuevos del endpoint:

- **Lote mixto**: 2 válidos, envelope roto, email en `properties` y un string → `{5, 2, 3}` y solo los
  2 válidos en la tabla.
- **Un solo INSERT**: con un oyente `before_cursor_execute` de SQLAlchemy se comprueba que un lote de
  20 eventos genera **una** sentencia `INSERT INTO telemetry_events`, con `executemany=False` y
  20 × 7 parámetros.
- **Reintento**: el mismo lote dos veces → `stored: 2` y luego `stored: 0`, con 2 filas en la tabla.
- **Fila según el contrato**: cada columna y los `tags` exactos de un `inbound_order_created`.
- **503** si falla la base de datos, y `emit()` que no lanza aunque falle.
- **El cuerpo no es `list[TelemetryEvent]`**: la firma del handler solo recibe `request`.

---

## 9. Cómo repetirlo y verlo en Supabase

```sh
# 1. La tabla (cualquiera de las dos)
uv run uvicorn services.api.main:app --reload       # la crea al arrancar (create_db_and_tables)
#   o pegar infra/supabase/telemetry_events.sql en Supabase > SQL Editor

# 2. Arrancar el backoffice (sin cambios: mismo NEXT_PUBLIC_TELEMETRY_ENDPOINT)
npm run dev --prefix uis/backoffice

# 3. Pruebas
uv run pytest
node tests/ui/run.mjs telemetry                              # SQLite desechable
TELEMETRY_E2E_SUPABASE=1 node tests/ui/run.mjs telemetry     # contra Supabase (deja un SKU E2E-TEL-…)
bash scripts/telemetry_mixed_batch.sh                        # lote mixto con curl a localhost:8000
```

Consultas útiles en **Supabase → SQL Editor**:

```sql
-- Los últimos eventos
select event_type, timestamp, source, tags
from telemetry_events order by timestamp desc limit 20;

-- Volumen de entradas y salidas por almacén y cliente (lo que necesitará Ana)
select event_type, tags->>'warehouse' as warehouse, tags->>'client_id' as client,
       count(*), sum((tags->>'quantity')::int) as units
from telemetry_events
where event_type in ('inbound_order_created', 'outbound_order_created')
group by 1, 2, 3 order by 1, 2, 3;

-- Comparación EE. UU. / España (lo que necesitará Thomas); usa el índice GIN
select count(*) from telemetry_events where tags @> '{"country": "ES"}';

-- Retraso entre captura e ingesta
select event_type, avg(created_at - timestamp) from telemetry_events group by 1;
```

---

## 10. Decisiones discutibles (y cómo defenderlas)

- **"¿Por qué `id` es el `eventId` y no un `gen_random_uuid()`?"** Porque es la clave de
  idempotencia. Con un id generado por la base, cada reintento de un lote crearía filas nuevas. El
  `eventId` ya es un UUID v4 que genera quien captura el evento.
- **"¿Por qué rechazar un evento que solo trae una propiedad de más?"** Porque esa propiedad de más
  puede ser justo el dato personal que el allowlist existe para frenar. Guardarlo "y ya lo limpiaremos"
  choca con una tabla inmutable. El evento se cuenta en `rejected` y el log dice qué campo sobraba.
- **"¿Por qué 200 si se rechazan eventos?"** Porque el lote, como unidad, se ha procesado. Un 4xx haría
  que el `TelemetryService` descartara también los válidos, y un 5xx haría que los reintentara para
  nada. El detalle va en el cuerpo (`rejected`) y en el log.
- **"¿Por qué un trigger, si el código ya no hace UPDATE?"** Porque la regla tiene que valer también
  para quien no pase por la API: el SQL Editor de Supabase, un script o un futuro desarrollador. El
  coste es que la retención (sección 11) necesitará un proceso que lo desactive de forma explícita, y
  eso es deliberado.
- **"¿Por qué `environment`, `schema_version` y `request_id` en `tags` y no como columnas?"** La
  estructura se fijó en ocho columnas. Esos tres campos se filtran poco. `tags` ya tiene índice GIN, así
  que buscar por `request_id` para cruzar con el log sigue siendo rápido.
- **"¿Por qué `emit()` escribe de forma síncrona dentro de una petición de inventario?"** Es una sola
  sentencia y ocurre **después** del commit del movimiento. Si falla, se registra en el log y la
  operación sigue. Si el retraso llegara a notarse, se podría mover a una tarea en segundo plano
  (`BackgroundTasks`) sin cambiar el contrato.

---

## 11. Lo que queda pendiente

- **Verificar el `userId`** contra el JWT. `sendBeacon` no puede mandar la cabecera `Authorization`,
  así que habría que incluir el token en el cuerpo, y eso cambiaría el frontend, que en este hito no
  se podía tocar.
- **Limitar el ritmo** del endpoint, que es abierto: hoy cualquiera puede mandar eventos que pasen la
  validación.
- **Retención**: el plan propone 25 meses para los eventos de negocio y 90 días para los de
  autenticación y errores. Con la tabla inmutable, harán falta un proceso explícito o particiones por
  mes que se puedan descartar enteras.
- **`database_connection_failed`**: si Supabase cae, ese evento no se puede guardar en el propio
  Supabase. Necesita otro destino (log externo o herramienta de alertas).
- Lo que ya estaba pendiente del hito 15: los 12 eventos restantes del catálogo, las pantallas de
  umbrales y conteos y el resto del seed de PR-6.

---

## 12. Archivos creados y modificados

| Archivo | Cambio |
|---|---|
| `services/telemetry_models.py` | **Nuevo.** Modelo `TelemetryEventRecord`: tabla `telemetry_events` con sus índices |
| `infra/supabase/telemetry_events.sql` | **Nuevo.** DDL para el SQL Editor, con RLS y trigger |
| `services/database.py` | Crea la tabla, le aplica RLS y el trigger (`telemetry_immutability_statements`) |
| `services/telemetry.py` | `TelemetryEnvelope` (laxo), `TelemetryReceipt` con `stored`/`rejected`, `event_row`, `accept_events`, `record_events` con bulk insert, `ingest_batch`, `open_session`. `TelemetryEvent` sin cambios |
| `services/routers/telemetry.py` | De stub a ingesta real: threadpool, 503 si falla Supabase |
| `scripts/telemetry_mixed_batch.sh` | **Nuevo.** Lote mixto con curl |
| `tests/telemetry/test_telemetry_storage.py` | **Nuevo.** Estructura, índices, mapeo, inmutabilidad |
| `tests/telemetry/test_telemetry_endpoint.py` | Reescrito para `received`/`stored`/`rejected` |
| `tests/telemetry/test_frontend_contract.py` | El servicio solo lee el código de estado |
| `tests/conftest.py` | Fixture `telemetry_store` (SQLite en memoria) |
| `tests/inventory/test_inventory_architecture.py` | `telemetry_events` en RLS y en la lista de tablas |
| `tests/ui/telemetry.mjs` | Checks TEL-13 a TEL-18 y modo `TELEMETRY_E2E_SUPABASE=1` |
| `tests/ui/lib/backoffice-app.mjs`, `tests/ui/README.md` | Opción `databaseUrl`; cómo ejecutar contra Supabase |
| `TELEMETRY_PLAN.md` | PR-5 cerrado; nueva sección 10.1 (almacenamiento) |
| `hito_16.md` | **Nuevo.** Este documento |
| `uis/` | **Sin cambios** |

Commits en `feature/telemetry-capture`:

1. `feat(telemetry): tabla telemetry_events en Supabase (hito 16, fase 1)`
2. `feat(telemetry): endpoint real POST /telemetry/events con persistencia (hito 16, fase 2)`
3. `test(telemetry): verificación end-to-end contra Supabase (hito 16, fase 3)`
4. `docs(telemetry): hito 16 y plan actualizado`

---

## 13. Lo que deberías poder explicar después de leer esto

1. Por qué una tabla de eventos tiene **pocas columnas fijas y un JSONB**, y qué va en cada sitio.
2. Qué hace un índice **GIN** y qué consulta lo aprovecha (`@>`).
3. Por qué tipar el cuerpo como `list[TelemetryEvent]` **rompe la aceptación parcial**, y cómo se
   evita con `model_validate` en un bucle.
4. Qué es un **bulk insert** y cómo se comprueba en un test que es uno solo.
5. Cómo `ON CONFLICT DO NOTHING` + `RETURNING` hacen la ingesta **idempotente** y el `stored` exacto.
6. Por qué la inmutabilidad se garantiza en **tres capas** y no solo con el código.
7. Por qué un lote mixto devuelve **200** y un fallo de Supabase **503**, pensando en el
   `TelemetryService`.
8. Por qué el frontend **no tuvo que cambiar**.
9. La diferencia entre `timestamp` y `created_at`.
10. Qué falta para que el endpoint sea seguro en producción (`userId`, límite de ritmo).

---

## 14. Glosario

| Término | Significado |
|---|---|
| **Ingesta** | Recibir, validar y guardar eventos que llegan de fuera |
| **Envelope laxo** | Validar solo la forma del lote (una lista) y dejar cada elemento para después |
| **`model_validate`** | Método de Pydantic que valida un dict contra un modelo y lanza `ValidationError` si no cumple |
| **Aceptación parcial** | Guardar lo válido de un lote aunque haya elementos inválidos |
| **Bulk insert** | Insertar muchas filas con una sola sentencia |
| **Idempotencia** | Repetir una operación sin cambiar el resultado |
| **`ON CONFLICT DO NOTHING`** | Cláusula de PostgreSQL/SQLite que ignora las filas cuya clave ya existe |
| **`RETURNING`** | Cláusula que devuelve columnas de las filas afectadas por un INSERT/UPDATE |
| **JSONB** | Tipo JSON binario de PostgreSQL, indexable |
| **Índice GIN** | Índice invertido: de cada clave/valor a las filas que lo contienen |
| **`@>`** | Operador "contiene" de JSONB |
| **Trigger** | Función que la base de datos ejecuta sola ante una operación |
| **RLS (Row Level Security)** | Reglas de PostgreSQL por fila; activado sin políticas, nadie sin privilegios ve la tabla |
| **Supavisor / pooler** | El intermediario de conexiones de Supabase |
| **Threadpool** | Hilos donde FastAPI ejecuta el código bloqueante para no frenar el bucle de eventos |
| **Inmutable** | Que no se puede modificar una vez escrito |
| **End-to-end (E2E)** | Prueba que recorre el sistema completo, del navegador a la base de datos |
