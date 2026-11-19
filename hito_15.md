# Hito 15 — Telemetría: captura en el frontend (y lo que solo ve el servidor)

Este documento explica, desde cero, cómo se ha pasado del **plan** de telemetría del Hito 14 a
**eventos reales** que salen del backoffice y llegan a la API. Está pensado para que alguien que nunca
ha instrumentado una aplicación termine sabiendo montar un servicio de telemetría en el navegador,
decidir qué captura el navegador y qué el servidor, y comprobar que funciona en la pestaña Network.

Los entregables formales son:

- [services/routers/telemetry.py](services/routers/telemetry.py): el stub `POST /telemetry/events`.
- [services/telemetry.py](services/telemetry.py): el modelo `TelemetryEvent` (el envelope), la
  validación contra `event-schemas.json` y el emisor de los eventos de la API.
- [uis/backoffice/app/lib/telemetry.ts](uis/backoffice/app/lib/telemetry.ts): el `TelemetryService`
  y la única función pública `track()`.
- La instrumentación de **14 eventos**: los 5 obligatorios del BRIEFING y las 9 oportunidades elegidas.
- [TELEMETRY_PLAN.md](TELEMETRY_PLAN.md) y [event-schemas.json](event-schemas.json), actualizados con
  las decisiones de este hito (catálogo 1.1.0).

---

## Índice

1. [El encargo](#1-el-encargo)
2. [Conceptos básicos](#2-conceptos-básicos)
3. [Qué se eligió capturar y quién lo captura](#3-qué-se-eligió-capturar-y-quién-lo-captura)
4. [Fase 1 — El stub del backend](#4-fase-1--el-stub-del-backend)
5. [Fase 2 — El TelemetryService del navegador](#5-fase-2--el-telemetryservice-del-navegador)
6. [Fase 3 — La instrumentación, evento a evento](#6-fase-3--la-instrumentación-evento-a-evento)
7. [Lo que solo ve el servidor](#7-lo-que-solo-ve-el-servidor)
8. [La privacidad, comprobada y no prometida](#8-la-privacidad-comprobada-y-no-prometida)
9. [Cambios en el plan y en el JSON](#9-cambios-en-el-plan-y-en-el-json)
10. [Problemas que aparecieron y cómo se resolvieron](#10-problemas-que-aparecieron-y-cómo-se-resolvieron)
11. [Cómo se comprobó](#11-cómo-se-comprobó)
12. [Cómo repetirlo y verlo en DevTools](#12-cómo-repetirlo-y-verlo-en-devtools)
13. [Decisiones discutibles (y cómo defenderlas)](#13-decisiones-discutibles-y-cómo-defenderlas)
14. [Lo que queda pendiente](#14-lo-que-queda-pendiente)
15. [Archivos creados y modificados](#15-archivos-creados-y-modificados)
16. [Lo que deberías poder explicar después de leer esto](#16-lo-que-deberías-poder-explicar-después-de-leer-esto)
17. [Glosario](#17-glosario)

---

## 1. El encargo

Segundo proyecto de la serie **Plan → Captura → Almacenamiento → Reporte**. El plan (Hito 14) decía
qué medir; ahora hay que **capturarlo**. El orden era obligatorio: primero el stub, después el
servicio y por último la instrumentación.

1. **Stub del backend**
   - `POST /telemetry/events` en un router propio dentro de `services/`, que acepta `{"events": [...]}`.
   - Escribe en el log cuántos eventos llegan y de qué tipo, y responde `200 {"received": N}`.
   - Un modelo Pydantic `TelemetryEvent` con los campos del envelope, que sirva sin cambios en la Fase 3.
   - La API lee `TELEMETRY_ENDPOINT` del entorno.
2. **TelemetryService en el frontend**
   - Una cola local.
   - Batch + debounce: enviar cada 10 s o al llegar a 20 eventos.
   - `navigator.sendBeacon` en `visibilitychange`.
   - Hasta 3 reintentos con espera exponencial y, después, descartar el lote.
   - Rellenar solo `eventId`, `sessionId`, `userId`, `timestamp`, `schemaVersion` y `requestId`.
   - Una sola función pública: `track(eventType, properties)`.
   - Ningún `fetch` de telemetría fuera del servicio.
   - La URL sale de `NEXT_PUBLIC_TELEMETRY_ENDPOINT`, nunca escrita en el código.
3. **Instrumentación**
   - Todas las métricas obligatorias.
   - Un suelo técnico:
     - errores no capturados (`window.onerror`, `unhandledrejection`, límites de error);
     - al menos una métrica de rendimiento;
     - las vistas de página de las secciones principales.
   - Extra: Web Vitals con `useReportWebVitals`, con la ruta en `properties`.
   - Eventos de autenticación capturados en la capa de auth, no en cada página. Un login fallido lleva
     el motivo y nunca el email ni la contraseña.
   - Sin PII.
   - Comprobar en DevTools → Network que los lotes llegan con 200.

Antes de empezar se eligieron, de las 21 oportunidades del plan, las **9 más útiles**. Además se
confirmaron tres decisiones de diseño (sección 3).

---

## 2. Conceptos básicos

### Capturar no es lo mismo que guardar

En este hito los eventos **viajan** y se **validan**, pero no se guardan: el endpoint es un *stub*,
una pieza provisional que cumple el contrato (recibe lotes y responde `{"received": N}`) sin hacer el
trabajo de verdad. Cuando llegue el proyecto de Almacenamiento, solo cambiará la función
`record_events` de `services/telemetry.py`. El frontend y el contrato HTTP no se tocarán.

### Cola, lote y debounce

Enviar un evento por petición HTTP sería caro: cada clic generaría una petición. El servicio guarda
los eventos en una **cola** (un array en memoria) y los envía juntos en un **lote**. ¿Cuándo?

- **A los 10 s del primer evento pendiente** (debounce): si llegan más eventos en ese tiempo, viajan
  todos juntos.
- **Al llegar a 20**: no hace falta esperar si el lote ya está lleno.

### Reintentos con espera exponencial (backoff)

Si el envío falla por algo que puede arreglarse solo (red caída, servidor en 5xx o 429), se reintenta
esperando cada vez el doble: **1 s, 2 s y 4 s**. Tras el tercer reintento el lote **se descarta**: la
telemetría nunca puede bloquear la aplicación ni acumular memoria sin límite. Un **4xx no se
reintenta**, porque si el servidor dice que el lote está mal, repetirlo no lo arregla.

### `sendBeacon` y `visibilitychange`

Cuando el usuario cierra la pestaña o navega fuera, los `fetch` en curso se cancelan.
`navigator.sendBeacon(url, datos)` es la API pensada para esto: el navegador **promete entregar** esos
datos aunque la página se esté destruyendo. Se dispara en:

- `visibilitychange` con `document.visibilityState === "hidden"`: el usuario cambia de pestaña,
  minimiza o cierra. En móviles es el último aviso fiable.
- `pagehide`: la página se descarga de verdad. Safari a veces solo dispara este.

### La petición previa de CORS (preflight)

El backoffice (`localhost:3001`) y la API (`localhost:8000`) son **orígenes distintos**. Para algunas
peticiones, el navegador pregunta antes a la API con un `OPTIONS` si las acepta: es el *preflight*.
Una petición con `Content-Type: application/json` lo necesita; una `text/plain`, no (es una petición
"simple"). **`sendBeacon` no puede hacer preflight**, así que el beacon se manda como `text/plain` y
la API lee el cuerpo a mano.

### Correlación: `requestId` y `sessionId`

- **`sessionId`**: un UUID guardado en `sessionStorage` (dura lo que la pestaña) que cambia en cada
  login y logout. Agrupa todo lo que hace una persona en una sesión.
- **`requestId`**: un UUID por llamada a la API. El backoffice lo manda en la cabecera `X-Request-Id`,
  la API lo usa en sus propios eventos y lo devuelve en la respuesta. Así un evento del navegador
  (`inbound_order_created`) se puede cruzar con la línea del log del servidor que registró la misma
  entrada.

### Web Vitals

Métricas de experiencia real de carga que mide el navegador:

| Métrica | Qué mide | Bueno |
|---|---|---|
| **TTFB** | Tiempo hasta el primer byte del servidor | < 800 ms |
| **FCP** | Primer contenido pintado | < 1,8 s |
| **LCP** | Pintado del elemento más grande | < 2,5 s |
| **INP** | Retraso entre una interacción y su respuesta visual | < 200 ms |
| **CLS** | Cuánto "salta" el contenido al cargar | < 0,1 |

Next.js las expone con el hook `useReportWebVitals`. CLS e INP no tienen un valor final hasta que la
página se oculta, y eso marca cuándo se envía el evento (sección 6.3).

---

## 3. Qué se eligió capturar y quién lo captura

### Las 9 oportunidades elegidas

Se priorizaron las que dan una decisión clara y cubren el suelo técnico del encargo:

| Evento | Por qué entra |
|---|---|
| `page_viewed` | Suelo técnico (vistas de página). Base de todo análisis de uso |
| `frontend_error_captured` | Suelo técnico (errores no capturados) |
| `page_load_recorded` | Suelo técnico (rendimiento) y actividad extra (Web Vitals) |
| `api_request_failed` | Distingue fallos de red del almacén de fallos del servidor |
| `login_failed` | Actividad extra (auth) |
| `session_expired` | Actividad extra (auth); mide si el token de 30 min interrumpe turnos |
| `outbound_order_rejected` | Pedido parado en el muelle: la oportunidad más urgente del inventario |
| `stock_loss_recorded` | Mermas por almacén y cliente: responsabilidad contractual |
| `order_form_abandoned` | Movimientos físicos que no se registran = discrepancias futuras |

Junto a los 5 obligatorios (`inbound_order_created`, `outbound_order_created`,
`stock_threshold_triggered`, `direct_stock_edit_rejected`, `inventory_discrepancy_detected`) suman **14**.

### ¿Navegador o servidor?

El encargo se titula "captura en el frontend", pero el plan del Hito 14 había puesto casi todos los
eventos de inventario en la API. Se confirmaron tres decisiones:

1. **`inbound_order_created`, `outbound_order_created`, `stock_loss_recorded` y
   `outbound_order_rejected` pasan al navegador.** Se capturan al recibir la respuesta de la API (201
   o 400), así que solo se emiten si la API confirmó el hecho. Para que el navegador pueda rellenar
   `stock_after`, la API lo añade ahora a la respuesta de las altas.
2. **`direct_stock_edit_rejected` se queda en el servidor.** Nadie fija stock desde el backoffice: no
   hay pantalla para eso. El intento llega por Swagger, `curl` o un script, y solo la API lo ve.
3. **`login_failed` pasa al navegador y sube a la versión 2.0.0.** Pierde los hashes HMAC del email y
   de la IP, porque el navegador no puede guardar una clave secreta. Su motivo pasa a ser
   `invalid_credentials | validation_error | network_error | server_error`. `session_expired` sigue
   siendo un evento aparte.

Al implementar apareció una cuarta decisión, que no estaba en la lista confirmada y conviene revisar:
**`stock_threshold_triggered` e `inventory_discrepancy_detected` también se quedan en el servidor.**

- Para saber si el stock **cruzó** el mínimo hace falta conocer el stock de antes y el de después del
  movimiento, dentro de la misma transacción. El navegador no lo sabe.
- Una discrepancia compara lo contado con el stock del sistema en el momento del conteo, que solo
  calcula la API.

Los tres eventos de servidor pasan por el mismo camino que los del navegador: el mismo envelope
(`TelemetryEvent`) y la misma función `record_events` del stub.

---

## 4. Fase 1 — El stub del backend

### El modelo `TelemetryEvent`

`services/telemetry.py` define el envelope con Pydantic y `extra="forbid"`, así que una clave de más
en el primer nivel hace que el lote se rechace. Cada campo tiene un formato:

| Campo | Regla |
|---|---|
| `eventId` | UUID v4 |
| `timestamp` | ISO 8601 en UTC con milisegundos: `2026-10-27T09:15:02.481Z` |
| `sessionId`, `userId` | UUID o `null`, pero la clave es **obligatoria** |
| `event_type` | `snake_case` con al menos un `_` |
| `schemaVersion` | SemVer `1.0.0` |
| `requestId` | UUID |
| `source` | `api` \| `backoffice_web` |
| `environment` | `development` \| `test` \| `production` |
| `properties` | objeto |

`TelemetryBatch` exige entre 1 y 100 eventos. Este modelo es el que se reutilizará en la Fase 3.

### El endpoint

`services/routers/telemetry.py`:

1. Lee el cuerpo **en crudo** (`await request.body()`), porque el beacon llega como `text/plain` y
   FastAPI solo parsea solo los `application/json`. Más de 256 KB → **413**.
2. `TelemetryBatch.model_validate_json(raw)`. Si el envelope no es válido → **422** con el mismo formato
   que el resto de la API y **sin devolver lo enviado** (`include_input=False`).
3. `record_events(batch.events)`:
   - valida cada evento contra su esquema de `event-schemas.json`;
   - escribe una línea `telemetry_schema_violation` por cada evento que se sale de su allowlist, con
     la ruta del campo y **nunca su valor**;
   - escribe una línea de resumen por lote:
     ```
     INFO:     [api.telemetry] telemetry batch received=6 valid=6 source=backoffice_web event_types=page_viewed,inbound_order_created,...
     ```
4. Responde `{"received": N}`.

**No pide JWT.** `sendBeacon` no puede añadir la cabecera `Authorization`; además, un lote no debe
perderse por haber caducado el token. El riesgo que abre (cualquiera puede mandar eventos) no importa
mientras el stub no guarde nada. La ingesta definitiva tendrá que verificar el `userId` (sección 14).

### Configuración y correlación

- `services/api/config.py` lee `TELEMETRY_ENDPOINT` y `TELEMETRY_ENVIRONMENT`.
- `telemetry_middleware` (en `services/api/main.py`):
  - lee `X-Request-Id` y `X-Session-Id`;
  - los guarda en `ContextVar`s (variables por petición), de donde los coge `telemetry.emit()`;
  - devuelve `X-Request-Id` en la respuesta.
- CORS añade `expose_headers=["X-Request-Id"]`, sin el cual el navegador no deja leer esa cabecera.
- Solo se aceptan UUIDs: un `X-Request-Id: <script>` se sustituye por uno nuevo.
- El `Dockerfile`, `docker-compose.yml` y `.dockerignore` copian o montan `event-schemas.json` en el
  contenedor de la API. Sin él, la API solo validaría el envelope.

---

## 5. Fase 2 — El TelemetryService del navegador

`uis/backoffice/app/lib/telemetry.ts`. Lo que hace cada parte:

### `track(eventType, properties)`

Es la **única** función pública de tracking y nunca lanza: si algo falla dentro, la pantalla sigue.
Tiene un tercer argumento opcional, `{ requestId }`, que solo usa la capa de API (`lib/*.ts`) para
correlacionar; los componentes nunca lo pasan. El servicio rellena el resto del envelope:

| Campo | De dónde sale |
|---|---|
| `eventId` | `crypto.randomUUID()`, o un UUID v4 hecho con `getRandomValues` si la página no es https ni localhost |
| `timestamp` | `new Date().toISOString()` **al llamar a `track`**, no al enviar |
| `sessionId` | `sessionStorage["trackflow.telemetry.session_id"]`; se rota con `startTelemetrySession()` en login y logout |
| `userId` | El `sub` del JWT guardado (el id de TinyDB); `null` sin sesión. Nunca el email |
| `schemaVersion` | La constante compartida `TELEMETRY_SCHEMA_VERSIONS` (`telemetry-schema.ts`) |
| `requestId` | El `X-Request-Id` de la llamada si lo pasa la capa de API; si no, uno nuevo |
| `source` / `environment` | `backoffice_web` / según `NODE_ENV` |

El tipo de `eventType` es la unión de las claves de `TELEMETRY_SCHEMA_VERSIONS`: un evento que no
esté en el catálogo **no compila**.

### La cola y el envío

```
track() ─► cola ─┬─ 20 eventos ────────────► flush() ─► fetch POST {events:[…]} (keepalive)
                 ├─ 10 s desde el primero ─► flush()        │
                 │                                          ├─ 2xx ─► listo
                 │                                          ├─ 4xx ─► descartado
                 │                                          └─ red / 5xx / 429 ─► reintento 1 s, 2 s, 4 s ─► descartado
                 └─ pestaña oculta / cerrada ─► flushOnHide() ─► sendBeacon(text/plain)
                                                               (también los lotes que esperaban reintento)
```

- Si `sendBeacon` devuelve `false` (el cuerpo pasa de unos 64 KB o su cola está llena), se hace un
  último intento con `fetch` y `keepalive`.
- **Sin `NEXT_PUBLIC_TELEMETRY_ENDPOINT` no se envía nada** y se avisa una sola vez por consola. Así un
  entorno sin configurar no rompe nada.

### `onHide(hook)`

Algunas cosas solo se pueden decidir en el último momento: las Web Vitals finales o un formulario
abandonado al cerrar la pestaña. `onHide` registra funciones que el servicio llama **justo antes** de
vaciar la cola por beacon, con el motivo: `hidden` (puede volver) o `pagehide` (se va).

---

## 6. Fase 3 — La instrumentación, evento a evento

La regla: **los componentes no construyen eventos**. Las propiedades se arman en
`app/lib/telemetry-events.ts`, que aplica el vocabulario del plan:

- `LA` → `los_angeles`;
- `client_id` como slug, igual que la API;
- las rutas como plantilla: `/talent/records/rec-123` → `/talent/records/[id]`.

Los componentes solo llaman a funciones con nombre de negocio.

### 6.1 Inventario (en `lib/inventory.ts`)

| Evento | Cuándo |
|---|---|
| `inbound_order_created` | `inventoryApi.registerEntry` recibe el 201 |
| `outbound_order_created` | `registerExit` recibe el 201 de un `dispatch` |
| `stock_loss_recorded` | `registerExit` recibe el 201 de un `loss` |
| `outbound_order_rejected` | `registerExit` recibe el 400 `Insufficient stock…` |

- El `X-Request-Id` se genera en `lib/inventory.ts` antes de la llamada, de modo que el evento y la
  petición llevan **el mismo**.
- `outbound_order_rejected` necesita el cliente y la categoría del SKU, que la respuesta 400 no trae.
  `registerExit` recibe ahora un segundo argumento opcional con el SKU elegido en el formulario.
- `available_quantity` sale del mensaje de la API ("Available: 4"), que ya se parseaba para mostrarlo
  en pantalla.

### 6.2 Autenticación (en `lib/auth.ts` y `ui/auth-guard.tsx`, nunca en una página)

- **`login_failed`**, en `login()`:
  - 401 → `invalid_credentials`;
  - 422 → `validation_error`;
  - sin respuesta → `network_error`;
  - 5xx → `server_error`.
- **`session_expired`**:
  - en `backofficeFetch` y `authFetch` (token caducado → `client_token_check`; 401 de la API →
    `api_401`);
  - en el guard, al cargar una pantalla con token caducado.

  Se emite **antes** de borrar el token, porque de él salen el `userId` y la edad de la sesión
  (`iat`). Una sola vez por token: las llamadas en vuelo que también ven el 401 no repiten.
  `had_unsaved_form` consulta el registro de formularios sucios (6.5).
- **Rotación de `sessionId`**: `login()` y `logout()` llaman a `startTelemetrySession()`.

### 6.3 Navegación y rendimiento (en `ui/telemetry-listener.tsx`)

Es un componente cliente que no pinta nada, montado en el layout raíz. Así el layout puede seguir
siendo de servidor, como recomienda la guía de Next 16 (`node_modules/next/dist/docs`).

- **`page_viewed`**:
  - se emite con cada cambio de `usePathname()`;
  - lleva la ruta como plantilla, la sección (`inventory`, `auth`…) y la pantalla anterior;
  - ignora la misma ruta repetida en menos de 2 s (re-renders y redirecciones del guard).
- **`page_load_recorded`**:
  - `useReportWebVitals` va acumulando TTFB, FCP, LCP, INP y CLS;
  - un hook `onHide` emite **un único evento** la primera vez que la pestaña se oculta;
  - `navigationType` de Next (`back-forward`, `back-forward-cache`, `prerender`…) se traduce al enum
    del plan (`navigate | reload | back_forward`).

### 6.4 Errores

- **`instrumentation-client.ts`** (raíz del backoffice): Next lo ejecuta **antes de hidratar**, así que
  los listeners `error` y `unhandledrejection` existen desde la primera línea.
- **`app/error.tsx`**: el límite de error de React. Captura lo que rompe un render y lo envía como
  `error_boundary`.
- **`api_request_failed`**:
  - en las funciones `request()` de `lib/auth.ts` (por donde pasan inventario, incidencias y
    proveedores) y de `lib/api.ts` (Talent Pipeline);
  - se dispara con un fallo de red, un tiempo agotado o un 5xx;
  - como mucho uno por (ruta, tipo de fallo) cada 30 s: sin red, todas las llamadas fallan a la vez.

`frontend_error_captured` **no envía el mensaje del error** (puede contener el nombre de un candidato).
Envía el tipo (`TypeError`) y un **fingerprint**: un hash FNV-1a de 64 bits del tipo y la primera línea
de la pila. Lo frenan dos límites:

- **Deduplicación**: un evento por fingerprint cada 60 s; las repeticiones se suman en `occurrences`.
- **Tope**: 20 errores por sesión, para que un bucle de render no inunde la ingesta.

### 6.5 Formularios abandonados (en `lib/form-abandonment.ts`)

`useFormAbandonment("inbound" | "outbound", form, EMPTY_FORM)` vigila el formulario:

- Está **sucio** si algún campo difiere del formulario vacío. Un envío correcto lo vacía, así que deja
  de estarlo.
- Si se **desmonta** sucio (el operario cambia de pantalla o cierra sesión) o la pestaña **se cierra**
  (`pagehide`), emite `order_form_abandoned` con:
  - los **nombres** de los campos rellenados, nunca sus valores;
  - el almacén;
  - el último error mostrado;
  - el tiempo en el formulario.
- **Ocultar** la pestaña no cuenta: el operario puede volver y terminar.

---

## 7. Lo que solo ve el servidor

### Prerrequisitos construidos: PR-1 y PR-2

- **PR-1, umbrales**:
  - tabla `stock_threshold`: un mínimo por SKU y almacén, con `min_stock > 0` y único por par;
  - `GET/POST /inventory/thresholds`.
  - El `POST` es un *upsert* (crea o reemplaza) y solo lo pueden usar `admin` y `manager` (403 al
    resto). Es POST y no PUT porque la API de inventario solo admite GET y POST: un test de
    arquitectura lo exige, y es la regla que hace posible detectar `direct_stock_edit_rejected`.
- **PR-2, conteos**:
  - tabla `stock_count`: lo contado, el stock del sistema en ese momento y el tipo
    (`cycle_count | full_audit`);
  - `GET/POST /inventory/counts`.
  - **Un conteo no corrige el stock**: la regla "el stock nunca se fija" sigue en pie.
- Las dos tablas tienen RLS en Supabase, como las de inventario.

### `stock_threshold_triggered`: disparo por flanco

En `register_exit`, después del `commit`:

```python
if min_stock is not None and available >= min_stock > stock_after:
    telemetry.emit("stock_threshold_triggered", {...})
```

Solo se emite cuando el stock **cruza** el mínimo hacia abajo (antes ≥ mínimo, después < mínimo).
Mientras siga por debajo, las siguientes salidas no repiten. Cuando una entrada lo devuelve por encima,
se **rearma**. El test recorre 100 → 60 → 40 (cruza) → 30 (no repite) → 100 → 40 (cruza otra vez,
por pérdida).

### `inventory_discrepancy_detected`

`register_count` calcula `system_quantity` con `available_stock`, guarda el conteo y, si no cuadra,
emite el evento:

- `quantity` = diferencia en valor absoluto;
- `difference` lleva el signo: negativo significa que faltan unidades.

Un conteo que cuadra se guarda y no emite nada, porque sirve para calcular la tasa.

### `direct_stock_edit_rejected`

`services/direct_stock_edit.py` reconoce los dos casos del plan:

| Caso | Ejemplo | Dónde se detecta |
|---|---|---|
| (a) `method_not_allowed` | `PUT /inventory/products/7 {"current_stock": 500}` → 405 | `telemetry_middleware`, con la respuesta ya calculada |
| (b) `forbidden_stock_field` | `POST /inventory/orders/inbound {…, "current_stock": 999}` → 422 `extra_forbidden` | El manejador de validación de `errors.py` |

- La respuesta al cliente **no cambia**: el módulo solo observa.
- Solo cuenta a usuarios autenticados: la hipótesis es "el personal intenta saltarse la
  trazabilidad".
- `client_channel` vale `backoffice_web` si la petición trae `X-Session-Id`, y `direct_api` si no.

### El emisor de la API

`telemetry.emit(event_type, properties, user_id=...)`:

- construye el mismo envelope que el navegador, con `source="api"` y los ids de correlación de la
  petición;
- descarta el evento si no cumple su esquema;
- se lo pasa a `record_events`, el mismo destino que los lotes del stub;
- **nunca lanza**: una excepción se escribe en el log y la salida de stock sigue registrada.

### El seed

`services/seed_inventory.py` fija ahora dos umbrales **antes** de las salidas (180 en la zapatilla de
LA, 160 en el sérum de Zaragoza), que esas salidas cruzan. Al final registra un conteo de los
auriculares de LA: 46 contados frente a 48 del sistema. Así salen **2 cruces de umbral y 1
discrepancia**, como pide el BRIEFING §5.

---

## 8. La privacidad, comprobada y no prometida

"Sin PII" no basta con escribirlo: se comprueba en cinco sitios.

1. **Allowlist en el esquema**: `additionalProperties: false`. El stub registra cualquier evento que
   se salga de ella, sin escribir el valor.
2. **El código no puede enviar valores tecleados**:
   - `order_form_abandoned` envía nombres de campo;
   - `frontend_error_captured` envía el tipo de error y un hash;
   - `login_failed` envía solo un enum.
3. **Rutas como plantilla**: ni ids ni query strings, que pueden contener búsquedas con nombres.
4. **Tests**:
   - el test Jest de `login_failed` comprueba que ni el email ni la contraseña aparecen en los eventos;
   - el de errores comprueba que no viaja el mensaje "…Ana García";
   - el de entradas comprueba que no viajan ni la referencia `PO-…` ni el nombre del producto.
5. **Navegador real**: la prueba `tests/ui/telemetry.mjs` busca el email, las dos contraseñas, la
   referencia del cliente y el mensaje del error en **todos** los eventos capturados de la red (TEL-07).

Los datos del Talent Pipeline no aparecen en ningún evento: esa sección solo genera `page_viewed`
(con `[id]` en la ruta), `api_request_failed` y errores.

---

## 9. Cambios en el plan y en el JSON

El plan y el JSON se generan con el mismo script, igual que en el Hito 14, así que no se pueden
contradecir. Los cambios (catálogo **1.1.0**):

- **Emisor**: cuatro eventos de inventario pasan a `source: backoffice_web`, con disparadores
  reescritos que apuntan al archivo exacto.
- **`login_failed` 2.0.0** (cambio **mayor**: se quitan propiedades):
  - sin `auth_method` ni hashes;
  - motivo con 4 valores;
  - sin PII;
  - pasa a **batch**, porque desde el navegador ya no se puede detectar un ataque y la decisión pasa
    a ser de usabilidad.
- **Fingerprint de errores**: SHA-256 → FNV-1a (ver 10.4).
- **Sección 6.1**: la frase "ningún evento del navegador necesita stream" ya no es cierta. Ahora dice
  que un lote de 10 s **sigue siendo stream** (< 1 min): lo que decide stream o batch es cómo se
  consume el evento, no cómo viaja. Quedan 6 eventos en stream.
- **Sección 10 nueva**: "Estado de la implementación", con dónde se captura cada evento.
  `x-implemented` en el JSON y la columna «Estado» de la tabla resumen marcan los 14.
- **PR-1, PR-2 y PR-3**, hechos. **PR-5**, como stub. **PR-6**, parcial.

---

## 10. Problemas que aparecieron y cómo se resolvieron

### 10.1 CLS e INP llegaban tarde

web-vitals publica el CLS y el INP finales en su propio listener de `visibilitychange`, registrado en
`document`. Si el servicio vaciaba la cola antes, el evento salía sin ellos. El evento sube de
`document` a `window`, así que el servicio escucha en **`window`**: su listener corre siempre después
de los de web-vitals.

### 10.2 Ocultar no es abandonar

La primera idea fue emitir `order_form_abandoned` en cualquier ocultación. Pero cambiar de pestaña para
mirar el albarán no es abandonar. Por eso `onHide` pasa el motivo, y el formulario solo reacciona a
`pagehide`.

### 10.3 Los literales BigInt no compilaban

`0xcbf29ce484222325n` da `TS2737` con el `target` del `tsconfig`. Se usan `BigInt("0x…")`.

### 10.4 jsdom no tiene `TextEncoder`, `Response` ni `Blob.text()`

- El hash recorre las unidades UTF-16 del texto: en ASCII da lo mismo que los bytes, y ya no necesita
  `TextEncoder`.
- Los tests usan respuestas simuladas, como `auth.test.ts`, y `FileReader` para leer el `Blob` del
  beacon.

Esto también explica por qué el fingerprint no es SHA-256: `crypto.subtle` es asíncrono y solo
existe en https o localhost, y un error puede ocurrir en cualquier sitio.

### 10.5 DevTools no siempre ve la respuesta de un beacon

En la prueba de Chrome, CDP registraba las peticiones `Ping` pero no su respuesta: la página ya se
había descargado. El 200 se comprueba también en el log de accesos de uvicorn, que registra todas
(TEL-02). En DevTools manual se ven bien si se marca **Preserve log** (sección 12).

### 10.6 La sesión "cambiaba" a mitad de la prueba

La primera versión de TEL-11 esperaba un solo `sessionId` en toda la prueba y falló con dos. Era
correcto: `login()` rota la sesión, así que lo de la pantalla de login va en otra. El test comprueba
ahora justo eso.

### 10.7 Los tests de arquitectura bloqueaban rutas nuevas

`test_inventory_architecture.py` fija la lista exacta de rutas, tablas con RLS y modelos del
inventario, y `test_api_characterization.py` fija las rutas de la API. Se actualizaron a propósito.
Que fallaran era la señal esperada de que había rutas nuevas.

### 10.8 La suite de Talent bloqueó la telemetría

La suite `talent` solo deja salir peticiones GET y bloquea cualquier POST local que no sea interno de
Next, para garantizar que la prueba no escribe nada. Con la telemetría activa, los lotes que iban al
stub contaban como escrituras y TAL-SAFE-02 falló (180/181). La política ahora admite **solo** `POST
/telemetry/events` hacia la API local de la prueba. La API externa de Talent sigue siendo de solo
lectura.

### 10.9 Bash no aceptaba algunos scripts largos

Los parches con muchas comillas y acentos fallaban al pasarlos por un heredoc de Bash
(`unexpected EOF`) antes de ejecutarse. Se escribieron como archivos `.py` en un directorio temporal.

---

## 11. Cómo se comprobó

| Comprobación | Resultado |
|---|---|
| `uv run pytest` (suite completa) | **921 / 921** |
| `tests/telemetry/test_telemetry_endpoint.py`: contrato del stub | 22 / 22 |
| `tests/inventory/test_inventory_telemetry.py`: eventos de la API y `stock_after` | 18 / 18 |
| `tests/telemetry/test_frontend_contract.py`: constante TS = JSON, URL sin escribir a mano | 6 / 6 |
| `tests/telemetry/test_event_schemas.py`: plan y JSON | 72 / 72 |
| `tests/inventory/test_inventory_seed.py`: incluye 2 cruces y 1 discrepancia | 7 / 7 |
| `npx jest` en `uis/backoffice` | **183 / 183** (35 nuevos en `telemetry.test.ts`) |
| `npx tsc --noEmit` | Sin errores |
| `npx eslint` sobre los archivos tocados | Sin errores |
| `node tests/ui/run.mjs telemetry` (Chrome real) | **14 / 14** |
| Resto de suites de UI (website, backoffice, incidents, suppliers, inventory, talent) | **181 / 181** |

La suite `telemetry` de Chrome hace un recorrido completo:

1. Un login fallido y uno correcto.
2. Una entrada.
3. Una salida rechazada por stock y una correcta.
4. Un formulario a medias abandonado.
5. Un error de JavaScript.
6. Salir de la página.

Después comprueba en la red:

- los lotes (TEL-01);
- el 200 de todos (TEL-02);
- el beacon `text/plain` (TEL-03);
- los 8 tipos de evento esperados (TEL-04);
- el log del stub (TEL-05);
- la **validación de cada evento contra su esquema** con el código de la API (TEL-06);
- la ausencia de PII (TEL-07);
- `login_failed` sin datos (TEL-08);
- el **mismo `X-Request-Id`** en la entrada y en su evento (TEL-09);
- las cantidades del rechazo (TEL-10);
- la sesión y el usuario seudónimo (TEL-11);
- que el destino sale de la variable de entorno (TEL-12).

ESLint marca 2 errores en `app/(protected)/talent/records/[id]/record-detail-client.tsx`, un archivo
que este hito no toca: ya estaban antes.

---

## 12. Cómo repetirlo y verlo en DevTools

```sh
# 1. Variables (una vez)
#    uis/backoffice/.env.local  (fuera de git):
#      NEXT_PUBLIC_TELEMETRY_ENDPOINT=http://localhost:8000/telemetry/events
#    .env de la raíz (opcional, son los valores por defecto):
#      TELEMETRY_ENDPOINT=http://localhost:8000/telemetry/events
#      TELEMETRY_ENVIRONMENT=development

# 2. Tablas nuevas y datos de ejemplo (umbrales y conteo incluidos)
uv run python -m services.seed_inventory

# 3. Arrancar
uv run uvicorn services.api.main:app --reload          # API en :8000
npm run dev --prefix uis/backoffice                    # backoffice (o docker compose up)

# 4. Pruebas
uv run pytest
npm test --prefix uis/backoffice
node tests/ui/run.mjs telemetry
```

Para verlo a mano:

1. Abrir el backoffice → DevTools → **Network**, marcar **Preserve log** y filtrar por `telemetry`.
2. Navegar y registrar una entrada. A los 10 s aparece un `POST events` de tipo `fetch` con estado
   **200**. En *Payload* se ve `{"events": [...]}` y en *Response*, `{"received": N}`.
3. Cambiar de pestaña y volver: aparece un `events` de tipo **`ping`** (el beacon), también con 200.
4. En la terminal de la API se ve cada lote:
   `telemetry batch received=… valid=… source=backoffice_web event_types=…`.

Antes de cada `POST` con `fetch` aparece un `OPTIONS`: es el preflight de CORS del `application/json`
(sección 2). El beacon no lo tiene.

---

## 13. Decisiones discutibles (y cómo defenderlas)

- **"¿Por qué capturar `outbound_order_created` en el navegador si el servidor lo sabe mejor?"** Lo
  pedía el encargo, y se emite con la **respuesta 201**, así que nunca cuenta algo que la API no
  confirmó. El riesgo es perder el evento si la pestaña se cierra entre el 201 y el envío. Lo cubre el
  beacon, y está documentado en el plan (7.3). La base de datos sigue siendo la contabilidad del
  stock; la telemetría mide ritmo y patrones.
- **"¿Por qué el stub no pide token?"** `sendBeacon` no puede mandarlo. Pedirlo haría perder justo
  los eventos de cierre (Web Vitals, abandonos). La verificación del `userId` irá en la ingesta
  definitiva, que podrá comprobar la firma de un token incluido en el cuerpo.
- **"¿Un lote de 10 s es stream?"** Sí, según el criterio del plan (< 1 min). Lo que separa stream de
  batch es si alguien actúa en minutos sobre el evento, no el mecanismo de transporte.
- **"¿Por qué FNV-1a y no SHA-256?"** El fingerprint agrupa errores; no protege ningún secreto. Un hash
  no criptográfico, síncrono y que funciona en cualquier contexto es la herramienta correcta.
- **"¿Por qué `track` tiene un tercer argumento si el encargo dice `track(eventType, properties)`?"**
  Es opcional y solo lo usa la capa de API para correlacionar con su `X-Request-Id`. Los componentes
  usan la firma de dos argumentos.

---

## 14. Lo que queda pendiente

- **Los 12 eventos restantes** del catálogo:
  - `user_logged_in`, `api_latency_recorded` y los errores de backend, entre otros;
  - `order_form_validation_failed` y `stock_warning_displayed`, que el navegador ya podría emitir.
- **Pantallas de umbrales y conteos** en el backoffice: hoy solo se gestionan por API.
- **Ingesta definitiva** (proyecto de Almacenamiento):
  - persistir;
  - deduplicar por `eventId`;
  - verificar el `userId` contra el JWT;
  - limitar el ritmo de un endpoint que hoy es abierto.
- **El resto del seed de PR-6** (más SKUs, entradas y salidas).

---

## 15. Archivos creados y modificados

| Archivo | Cambio |
|---|---|
| `services/routers/telemetry.py` | **Nuevo.** Stub `POST /telemetry/events` |
| `services/telemetry.py` | **Nuevo.** `TelemetryEvent`, validación contra el JSON, `emit`, correlación, vocabulario |
| `services/direct_stock_edit.py` | **Nuevo.** Detección de `direct_stock_edit_rejected` |
| `services/api/main.py` | Router de telemetría, `telemetry_middleware`, `expose_headers` |
| `services/api/errors.py` | Caso (b) de `direct_stock_edit_rejected` en el manejador 422 |
| `services/api/config.py` | `TELEMETRY_ENDPOINT`, `TELEMETRY_ENVIRONMENT` |
| `services/models.py`, `services/database.py` | Tablas `stock_threshold` y `stock_count` (con RLS) |
| `services/schemas.py` | `stock_after` en las altas; esquemas de umbrales y conteos |
| `services/inventory_service.py` | Umbrales, conteos y los dos eventos de servidor |
| `services/routers/inventory.py` | `/inventory/thresholds`, `/inventory/counts`, `stock_after` |
| `services/seed_inventory.py` | 2 umbrales y 1 conteo |
| `pyproject.toml`, `uv.lock`, `services/requirements.txt` | `jsonschema` pasa a dependencia de la aplicación |
| `uis/backoffice/app/lib/telemetry.ts` | **Nuevo.** `TelemetryService` y `track()` |
| `uis/backoffice/app/lib/telemetry-schema.ts` | **Nuevo.** Constante `TELEMETRY_SCHEMA_VERSIONS` |
| `uis/backoffice/app/lib/telemetry-events.ts` | **Nuevo.** Propiedades, throttle y deduplicación de cada evento |
| `uis/backoffice/app/lib/form-abandonment.ts` | **Nuevo.** Hook `useFormAbandonment` |
| `uis/backoffice/app/ui/telemetry-listener.tsx` | **Nuevo.** `page_viewed` y Web Vitals |
| `uis/backoffice/instrumentation-client.ts` | **Nuevo.** Errores globales |
| `uis/backoffice/app/lib/auth.ts` | Cabeceras de correlación, `login_failed`, `session_expired`, `api_request_failed`, rotación de sesión |
| `uis/backoffice/app/lib/api.ts` | `api_request_failed` |
| `uis/backoffice/app/lib/inventory.ts` | Eventos de inventario con el `X-Request-Id` de la llamada |
| `uis/backoffice/app/ui/auth-guard.tsx` | `session_expired` y rotación al cerrar sesión |
| `uis/backoffice/app/error.tsx`, `app/layout.tsx` | Límite de error y `TelemetryListener` |
| `inbound-client.tsx`, `outbound-client.tsx` | Hook de abandono y SKU para el rechazo |
| `uis/backoffice/.env.local` | **Nuevo, fuera de git.** `NEXT_PUBLIC_TELEMETRY_ENDPOINT` |
| `.env.example`, `docker-compose.yml`, `Dockerfile`, `.dockerignore` | Variables de telemetría y `event-schemas.json` en la imagen |
| `TELEMETRY_PLAN.md`, `event-schemas.json` | Catálogo 1.1.0 (sección 9) |
| `tests/telemetry/test_telemetry_endpoint.py`, `test_frontend_contract.py` | **Nuevos** |
| `tests/inventory/test_inventory_telemetry.py` | **Nuevo** |
| `tests/inventory/test_inventory_architecture.py`, `test_inventory_seed.py`, `tests/test_api_characterization.py`, `tests/telemetry/test_event_schemas.py` | Rutas, tablas y ejemplo actualizados |
| `uis/backoffice/__tests__/telemetry.test.ts` | **Nuevo.** 35 tests |
| `tests/ui/telemetry.mjs` | **Nuevo.** Suite de Chrome real |
| `tests/ui/run.mjs`, `tests/ui/lib/*.mjs`, `tests/ui/README.md` | Suite registrada; endpoint de telemetría de la prueba; cabeceras y cuerpo de cada petición |
| `tests/ui/talent.mjs` | Permite el POST de telemetría al stub local (10.8) |
| `hito_15.md` | **Nuevo.** Este documento |

---

## 16. Lo que deberías poder explicar después de leer esto

1. Qué es un **stub** y por qué permite construir el frontend antes que el almacenamiento.
2. Por qué se envía en **lotes** y qué hacen el debounce de 10 s y el tope de 20.
3. Cómo funcionan los **reintentos con backoff** y por qué un 4xx no se reintenta.
4. Para qué sirven **`sendBeacon`** y `visibilitychange`, y por qué el beacon va como `text/plain`
   (preflight de CORS).
5. De dónde sale cada campo del **envelope** en el navegador, y por qué el `timestamp` es el de la
   captura.
6. Cómo un **`X-Request-Id`** une un evento del navegador con el log del servidor.
7. Qué eventos tiene que capturar **el servidor** y por qué (stock antes/después, intentos que no
   vienen del backoffice).
8. Qué es el **disparo por flanco** con rearme, con el ejemplo del test.
9. Cómo se garantiza **"sin PII"** en cinco capas, no solo con una promesa.
10. Por qué `login_failed` tuvo que subir a **2.0.0** al cambiar de emisor.

---

## 17. Glosario

| Término | Significado |
|---|---|
| **Stub** | Implementación provisional que cumple el contrato sin hacer el trabajo final |
| **TelemetryService** | La clase del navegador que encola, agrupa y envía los eventos |
| **Lote (batch)** | Varios eventos enviados en una sola petición |
| **Debounce** | Esperar un tiempo a que se acumulen cosas antes de actuar |
| **Backoff exponencial** | Reintentar esperando cada vez el doble (1 s, 2 s, 4 s…) |
| **`sendBeacon`** | API del navegador que entrega datos aunque la página se cierre |
| **`visibilitychange` / `pagehide`** | Eventos del navegador al ocultar / descargar la página |
| **Preflight (CORS)** | Petición `OPTIONS` previa que el navegador hace entre orígenes distintos |
| **`keepalive`** | Opción de `fetch` que deja terminar la petición aunque se navegue fuera |
| **Correlación** | Unir eventos y logs del mismo hecho con ids compartidos (`requestId`, `sessionId`) |
| **`ContextVar`** | Variable de Python con un valor distinto por petición |
| **Upsert** | Crear si no existe, reemplazar si existe |
| **Disparo por flanco** | Emitir al cruzar un límite, no mientras se está al otro lado |
| **Rearme** | Volver a permitir el disparo cuando se recupera el estado inicial |
| **Web Vitals** | TTFB, FCP, LCP, INP y CLS: experiencia real de carga e interacción |
| **`useReportWebVitals`** | Hook de Next.js que entrega esas métricas |
| **`instrumentation-client.ts`** | Archivo que Next ejecuta en el navegador antes de hidratar |
| **Límite de error (Error Boundary)** | Componente que captura un fallo de render y muestra una alternativa |
| **Fingerprint** | Hash que agrupa errores iguales sin enviar su mensaje |
| **FNV-1a** | Función hash rápida y no criptográfica |
| **Formulario sucio** | Formulario con cambios sin enviar |
| **CDP** | Chrome DevTools Protocol: lo que usan DevTools y el arnés de pruebas para observar la red |
