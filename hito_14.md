# Hito 14 — Plan de Telemetría del sistema de inventario

Este documento explica, desde cero, **qué es la telemetría**, cómo se ha diseñado el Plan de
Telemetría de TrackFlow, qué decisiones se tomaron y **por qué**. Está pensado para que alguien que
nunca ha diseñado un evento termine de leerlo sabiendo hacer un plan así por su cuenta y defendiendo
cada decisión delante de quien lo evalúe.

Los entregables formales son tres:

- [TELEMETRY_PLAN.md](TELEMETRY_PLAN.md): el plan completo (catálogo, envelope, esquemas por
  evento, estrategia de entrega, riesgos y guía para instrumentar).
- [event-schemas.json](event-schemas.json): los esquemas de todos los eventos en JSON Schema
  draft-07, validables con cualquier librería.
- [tests/telemetry/test_event_schemas.py](tests/telemetry/test_event_schemas.py): el test que
  comprueba que el JSON es válido y que coincide con el plan y con el código.

Este hito es la versión "para estudiar" de todo eso. El plan es la referencia; aquí está el
razonamiento.

---

## Índice

1. [El encargo](#1-el-encargo)
2. [Conceptos básicos](#2-conceptos-básicos)
3. [Dónde se hizo y qué se miró antes de escribir](#3-dónde-se-hizo-y-qué-se-miró-antes-de-escribir)
4. [Fase 1 — El catálogo de oportunidades, paso a paso](#4-fase-1--el-catálogo-de-oportunidades-paso-a-paso)
5. [Lo que el sistema todavía no tiene (prerrequisitos)](#5-lo-que-el-sistema-todavía-no-tiene-prerrequisitos)
6. [Fase 2 — El Event Envelope y los esquemas](#6-fase-2--el-event-envelope-y-los-esquemas)
7. [Fase 3 — Stream o batch, y cómo frenar los eventos ruidosos](#7-fase-3--stream-o-batch-y-cómo-frenar-los-eventos-ruidosos)
8. [Riesgos y exclusiones: lo que se decidió NO medir](#8-riesgos-y-exclusiones-lo-que-se-decidió-no-medir)
9. [Cómo se construyeron el plan y el JSON sin que se contradigan](#9-cómo-se-construyeron-el-plan-y-el-json-sin-que-se-contradigan)
10. [Problemas que aparecieron y cómo se resolvieron](#10-problemas-que-aparecieron-y-cómo-se-resolvieron)
11. [Cómo se comprobó](#11-cómo-se-comprobó)
12. [Decisiones discutibles (y cómo defenderlas)](#12-decisiones-discutibles-y-cómo-defenderlas)
13. [El siguiente paso: la captura](#13-el-siguiente-paso-la-captura)
14. [Archivos creados y modificados](#14-archivos-creados-y-modificados)
15. [Lo que deberías poder explicar después de leer esto](#15-lo-que-deberías-poder-explicar-después-de-leer-esto)
16. [Glosario](#16-glosario)

---

## 1. El encargo

El BRIEFING de telemetría (CONTEXT-10) abre una serie de cuatro proyectos: **Plan → Captura →
Almacenamiento → Reporte**. Este hito es el primero: decidir **qué** se mide, **con qué forma** y
**cómo se entrega**, sin escribir todavía el código que emite los eventos.

El checklist pedía tres fases:

1. **Catálogo exhaustivo de oportunidades de datos**
   - Incluir las 5 métricas obligatorias del BRIEFING (son el piso, no el techo).
   - Mapear el flujo de inventario con al menos **5 puntos de instrumentación**, incluyendo el intento
     de modificar stock directamente, las validaciones fallidas y la activación del umbral mínimo.
   - Explorar el resto del backoffice: autenticación, rendimiento, errores de frontend, navegación.
   - Para cada evento, completar la frase *"Capturamos X porque necesitamos saber Y, lo que nos
     permite tomar la decisión Z"*. Si no se puede completar, el evento se descarta.
   - Clasificar cada evento como **obligatorio** u **oportunidad identificada**.
2. **Diseño del Event Envelope**
   - Un envelope común con `eventId`, `timestamp` ISO 8601, `sessionId`, `userId`, `event_type`,
     `schemaVersion`, `requestId` y `properties`.
   - Los obligatorios + al menos **8 eventos adicionales** de **3 categorías** distintas, con nombres
     `entidad_acción`.
   - Una **allowlist** de propiedades por evento, y para cada propiedad: nombre, tipo, si es
     obligatoria, descripción y si es dato sensible.
   - Exportarlo todo a `event-schemas.json`.
3. **Estrategia de entrega**
   - Stream o batch para cada evento, justificado por la **urgencia de negocio**, no por gusto técnico.
   - Throttle/debounce para los eventos de alta frecuencia.
   - Una sección de **riesgos y exclusiones**.

Y una advertencia importante: un plan que solo cubra el mínimo **no se acepta**. El catálogo tiene que
ser amplio y estar fundamentado.

---

## 2. Conceptos básicos

### ¿Qué es la telemetría?

Es que el propio sistema **cuente lo que pasa** mientras se usa, enviando pequeños mensajes
estructurados llamados **eventos**. "Se ha registrado una salida de 2 auriculares en Los Ángeles"
es un evento. Sumando miles de eventos se responden preguntas de negocio: ¿cuántos pedidos despacha
Zaragoza por hora? ¿Qué cliente se queda sin stock más a menudo?

### Evento, log y métrica: no son lo mismo

| | Qué es | Ejemplo en TrackFlow | Para quién |
|---|---|---|---|
| **Log** | Texto libre para depurar | `INFO: [api.timing] GET /inventory/products → 200 \| 279.9ms` | Desarrolladores, cuando algo falla |
| **Evento** | Hecho de negocio con forma fija y campos con nombre | `outbound_order_created` con `warehouse`, `client_id`, `quantity`… | Analistas, dashboards, alertas |
| **Métrica** | Número agregado en el tiempo | "p95 de `/inventory/products` en el último minuto = 310 ms" | Monitorización |

Un log se lee; un evento **se agrega**. Por eso un evento necesita una forma exacta: si un día
`warehouse` vale `LA` y otro `los_angeles`, el dashboard de Ana cuenta dos almacenes en vez de uno.

### Hipótesis → decisión: "nada por si acaso"

La regla más importante del plan. Medir cuesta (código, almacenamiento, privacidad, ruido), así que
cada evento tiene que justificar su existencia con una **decisión concreta que alguien va a tomar**.

> Capturamos `outbound_order_rejected` porque necesitamos saber cuándo un operario intenta despachar
> más de lo que hay (o la demanda supera al stock, o el stock del sistema está mal), lo que nos
> permite tomar la decisión de lanzar un conteo inmediato de ese SKU.

Si no encuentras la decisión, el evento es "por si acaso" y se descarta. Así se descartaron, por
ejemplo, las consultas de un SKU (sección 8).

### El Event Envelope

Es el **sobre** común que llevan todos los eventos, como el remite y la fecha de una carta. Dentro
del sobre va la carta concreta (`properties`), que cambia según el evento. Gracias al sobre, todos los
eventos se pueden guardar en la misma tabla, ordenar por fecha, unir por sesión o por petición, y
deduplicar, sin conocer cada tipo de evento.

### Allowlist

Una **lista cerrada** de las claves que un evento puede llevar. Todo lo que no esté en la lista se
rechaza. La alternativa (una *blocklist*, "todo menos el email") falla en cuanto alguien añade un campo
nuevo sin pensar: el día que el formulario tenga "nombre del destinatario", se colaría solo. Con la
allowlist, un campo nuevo no sale hasta que alguien lo añade **a propósito** y lo revisa.

En JSON Schema se expresa con `"additionalProperties": false`.

### PII y seudonimización

**PII** (*Personally Identifiable Information*) es cualquier dato que identifica a una persona: email,
nombre, IP, teléfono, dirección. En la UE (Zaragoza) lo regula el RGPD.

- **Anonimizar**: que no se pueda volver a saber quién era. Irreversible.
- **Seudonimizar**: cambiar el dato por un código que, sin una pieza secreta, no se puede deshacer.
  El `userId` (UUID de TinyDB) es un seudónimo: solo TinyDB sabe a qué email corresponde.
- **HMAC**: una "huella" del dato calculada con una **clave secreta**. El mismo email da siempre la
  misma huella (así se pueden contar intentos sobre la misma cuenta), pero sin la clave no se puede
  adivinar el email probando emails (cosa que sí se podría con un hash normal). Se usa en `login_failed`.

### Stream y batch

- **Stream** (tiempo real): cada evento sale en cuanto ocurre y llega en segundos. Caro y exigente
  (hay que tener algo escuchando siempre).
- **Batch** (lotes): los eventos se juntan y se envían cada cierto tiempo (5 min, cada hora, al día).
  Barato y simple.

La pregunta para elegir no es técnica sino de negocio: **¿alguien tiene que actuar antes de que
llegue el siguiente lote?**

### Throttle, debounce, deduplicación, agregación y muestreo

Cinco formas de evitar que un evento muy frecuente inunde el sistema:

| Técnica | Idea | Ejemplo en el plan |
|---|---|---|
| **Debounce** | Esperar a que algo deje de cambiar antes de emitir | Aviso de stock: esperar 800 ms a que el operario termine de teclear la cantidad |
| **Throttle** | Como máximo N eventos por intervalo | Fallos de red: uno por ruta cada 30 s |
| **Deduplicación** | No repetir el mismo evento, contar las repeticiones | Errores de frontend: uno por huella cada 60 s con `occurrences` |
| **Agregación** | Enviar un resumen en vez de cada caso | Latencia: un evento por ruta y minuto con p50/p95/máx |
| **Muestreo** | Enviar solo un porcentaje | Web Vitals al 25 % si hay más de 1.000 cargas al día |

### JSON Schema

Un formato estándar para describir **qué forma tiene que tener un JSON**: qué claves, de qué tipo, qué
valores. Hay librerías en todos los lenguajes que comprueban si un JSON cumple un esquema. Por eso el
plan exporta los eventos a `event-schemas.json`: el mismo archivo lo usarán el emisor de backend, la
ingesta y los tests. Se usa la versión **draft-07**, la más soportada.

Las claves que empiezan por `x-` (`x-hypothesis`, `x-delivery`…) son **metadatos propios**: los
validadores las ignoran, pero así el JSON lleva también la hipótesis, la entrega y la PII de cada evento.

### Idempotencia

Que repetir una operación no cambie el resultado. Si el navegador reenvía un lote porque no recibió
respuesta, los eventos llegan dos veces; como cada uno lleva un `eventId` único, la ingesta descarta el
segundo. Sin eso, los volúmenes de Ana saldrían inflados.

---

## 3. Dónde se hizo y qué se miró antes de escribir

**El CONTEXT-10 estaba en la copia del proyecto** (`Copia Proyecto/…/audit/CONTEXTS/`), pero la copia
no tiene el sistema de inventario: ni `services/inventory_service.py` ni las pantallas de
`uis/backoffice/app/(protected)/inventory`. La Fase 1 pide mapear el flujo **real**, así que el plan se
escribió en el proyecto principal y el CONTEXT-10 se copió a su `audit/CONTEXTS/`.

Antes de escribir una sola línea del plan se leyó:

| Archivo | Qué se buscaba |
|---|---|
| `services/models.py`, `services/schemas.py` | Nombres reales de los campos (`client_name`, `warehouse = LA/ZGZ`, `exit_type`), y que los schemas de petición tienen `extra="forbid"` |
| `services/inventory_service.py` | Dónde se hace el `commit` de cada movimiento y dónde se lanza `InsufficientStock` |
| `services/routers/inventory.py` | Qué rutas existen (y que **no** existe ninguna para editar o borrar) |
| `services/api/errors.py` | Los manejadores de 422, 503 y 500 ya centralizados |
| `services/api/routes/auth.py`, `security.py`, `config.py` | Login, token de 30 min, recuperación de contraseña |
| `uis/backoffice/app/lib/auth.ts`, `api.ts`, `inventory.ts` | Cómo detecta el frontend la sesión caducada y los fallos de red |
| Formularios de entrada y salida | La validación en cliente y el aviso de stock insuficiente (`showWarning`) |
| `services/seed_inventory.py` | Los datos semilla, para los ejemplos (SoundWave Electronics, `TEC-EAR-001`…) |

Esto es lo que hace que el plan diga "se dispara en `services/inventory_service.py:151`" y no "se
dispara cuando se crea una orden": otra persona puede instrumentarlo sin preguntar.

---

## 4. Fase 1 — El catálogo de oportunidades, paso a paso

### 4.1 Primero, el piso: las 5 métricas obligatorias

Se copiaron del BRIEFING **con los nombres exactos**: `inbound_order_created`,
`outbound_order_created`, `stock_threshold_triggered`, `direct_stock_edit_rejected` e
`inventory_discrepancy_detected`, con los campos mínimos `warehouse`, `client_id`, `product_id`,
`product_category` y `quantity`.

Se añadió `country` (`US`/`ES`), derivado de `warehouse`. El BRIEFING dice que estas métricas se
agregarán "por almacén, por cliente y por país" para el dashboard de Thomas; si el país no está en el
evento, cada informe tendría que deducirlo con un join.

Y al ponerlas junto al código apareció lo primero interesante: **dos de las cinco no se pueden
emitir hoy**, porque el sistema no tiene umbrales mínimos ni registro de conteos físicos (sección 5).

### 4.2 Mapear el flujo de inventario

Se siguió el recorrido de un operario por el código, desde el login hasta que la orden queda en la
base de datos, apuntando cada sitio donde pasa algo que alguien querría saber. Salieron **12 puntos**
(el mínimo era 5), y el plan los dibuja con un diagrama:

- **Intento directo de modificar stock (I-9)**. En TrackFlow el stock nunca se fija: se calcula
  (entradas − salidas). ¿Cómo "intenta" alguien saltárselo si no hay ningún botón? Por la API: un `PUT`
  a `/inventory/products/{id}` (la API responde 405 porque esa ruta no existe a propósito) o un `POST`
  con `current_stock` en el cuerpo (los schemas tienen `extra="forbid"`, así que Pydantic lo rechaza con
  422 `extra_forbidden`). El evento se emite desde un middleware que reconoce esos dos casos.
- **Validaciones fallidas (I-4, I-5, I-6)**. Hay tres niveles distintos y por eso tres eventos:
  la validación del formulario en el navegador, el 422 de la API (datos mal formados) y el 400 de
  stock insuficiente (datos bien formados pero imposibles). Mezclarlos impediría saber si el problema
  es de diseño del formulario, de integraciones mal hechas o de stock real.
- **Activación del umbral (I-8)**. Después de cada salida, si el stock cruza el mínimo hacia abajo.

### 4.3 Explorar el resto del backoffice

La advertencia del enunciado era clara: no vale con cumplir el mínimo. Se recorrieron las demás áreas
buscando **lo que ya existe pero nadie ve**:

- `app/error.tsx` solo hace `console.error`: si una pantalla se rompe en la tablet de un operario, el
  equipo **nunca se entera**. → `frontend_error_captured`.
- `errors.py` ya captura los 500 y los 503 de Supabase, pero solo los escribe en el log.
  → `api_error_occurred`, `database_connection_failed`.
- Si Resend falla al mandar el email de recuperación, hoy solo queda una línea en el log, y el usuario
  se queda sin acceso. → `password_reset_email_failed`.
- El token dura 30 minutos y, al caducar, el frontend borra la sesión. ¿Pierde el operario el
  formulario que estaba rellenando? → `session_expired` con `had_unsaved_form`.
- El Hito 11 mejoró Lighthouse en laboratorio, pero no hay ningún dato de usuarios reales.
  → `page_load_recorded`.
- El seed necesita `CLT-SNK-W-42-Z` para tener el mismo producto en Zaragoza, porque el código de SKU es
  único global. Eso es una tensión del modelo de datos que vale la pena medir. → `product_creation_rejected`.

### 4.4 La frase de cada evento y la clasificación

Cada uno de los 26 eventos tiene su frase completa en la sección 2.4 del plan. Escribirlas sirve de
filtro: varias ideas iniciales no pasaron (sección 8). Después, cada evento se etiquetó como
**obligatorio** (5) u **oportunidad** (21), repartidas en inventario (7), autenticación (5),
errores (5), rendimiento (2) y navegación (2).

---

## 5. Lo que el sistema todavía no tiene (prerrequisitos)

Un plan escrito contra el código real encuentra huecos. Mejor documentarlos ahora que descubrirlos a
mitad de la captura. El plan los numera de PR-1 a PR-6:

| Id | Hueco | Por qué importa |
|---|---|---|
| PR-1 | No hay **stock mínimo** por SKU y almacén | Sin umbral no hay `stock_threshold_triggered`. Se propone una tabla `stock_threshold`; es configuración, no stock, así que no rompe la regla de "el stock nunca se fija". |
| PR-2 | No hay **registro de conteos** físicos | Sin conteo no hay `inventory_discrepancy_detected`. Se propone `POST /inventory/counts`, que registra el conteo **sin corregir** el stock: la corrección sigue pasando por una salida `loss` o una entrada. |
| PR-3 | No hay **ids de correlación** | El envelope necesita `sessionId` y `requestId`; hoy ni el frontend los genera ni la API los lee. |
| PR-4 | No hay **id de cliente**, solo `client_name` | Se usa un slug determinista mientras no exista una entidad `Client`. |
| PR-5 | No hay **punto de entrada** para los eventos del navegador | Hace falta `POST /telemetry/events`. |
| PR-6 | El **seed** se queda corto frente al BRIEFING §5 | Hacen falta 8–10 SKUs, 15–20 entradas y salidas, 2 cruces de umbral y 1 discrepancia. |

---

## 6. Fase 2 — El Event Envelope y los esquemas

### 6.1 Las decisiones del envelope, una a una

| Campo | Decisión | Por qué |
|---|---|---|
| `eventId` | UUID v4 | Clave de idempotencia (sección 2). |
| `timestamp` | ISO 8601 en **UTC con milisegundos** y `Z` final | Los Ángeles y Zaragoza están a 9 horas: si cada uno guardara su hora local, ordenar eventos de los dos almacenes sería un lío. Los milisegundos permiten ordenar una salida y el cruce de umbral que provoca. |
| `sessionId` | UUID en `sessionStorage`, nuevo en cada login/logout; puede ser `null` | Une todo lo que hizo una persona en una sesión de navegador. Es `null` cuando no hay backoffice (Swagger, scripts) o en eventos agregados. |
| `userId` | El UUID de TinyDB; **lo pone siempre el servidor** desde el JWT | Si lo pusiera el navegador, cualquiera podría atribuir eventos a otro operario. |
| `requestId` | UUID por llamada, viaja en la cabecera `X-Request-Id` | Une el evento del navegador, la petición, la línea del log y el evento del backend. |
| `schemaVersion` | SemVer **por evento** | Cambiar un evento no obliga a versionar los otros 25. |
| `source`, `environment` | Añadidos al mínimo del checklist | Saber quién emite y poder filtrar `production` en los informes. |

Una decisión que parece pequeña: las claves **siempre están**, aunque valgan `null`. Así un informe
nunca tiene que distinguir entre "no se envió" y "no aplicaba".

### 6.2 Traducir los datos del sistema al idioma del BRIEFING

El código guarda `LA`/`ZGZ`; el BRIEFING pide `los_angeles`/`zaragoza`. El código tiene `client_name`;
el BRIEFING pide `client_id`. Las reglas exactas están en la sección 4.3 del plan:

- `LA → los_angeles → US`, `ZGZ → zaragoza → ES`, en **un único diccionario** del emisor.
- `client_id` = slug de `client_name`: minúsculas, sin acentos, lo que no sea letra o número pasa a `_`.
  `GlowLab Cosmetics → glowlab_cosmetics`.
- `product_id` = el código SKU (`TEC-EAR-001`), nunca el nombre del producto.

### 6.3 La taxonomía `entidad_acción`

Todos los nombres siguen la misma gramática: **entidad primero, verbo en participio al final**,
en `snake_case`. Y los verbos son una lista cerrada (`created`, `rejected`, `failed`, `triggered`,
`detected`, `recorded`…), cada uno con un significado fijo. Por ejemplo, `rejected` es "el sistema
dice que no por una regla de negocio" y `failed` es "algo se rompió". Así, solo con leer el nombre de
un evento ya sabes de qué tipo es.

### 6.4 La ficha de cada evento

Cada evento del catálogo (sección 5 del plan) lleva: descripción, disparador exacto en el código,
emisor, consumidor, entrega, throttle, PII y una tabla con su allowlist (nombre, tipo, obligatoria,
valores permitidos y descripción). En el JSON, lo mismo, más `additionalProperties: false`.

### 6.5 La PII, caso por caso

Lo más delicado del plan fue decidir qué **no** sale:

- El **`tracking_number`** existe en cada despacho, pero el BRIEFING dice que los datos del
  transportista y del destinatario pertenecen a la última milla. No sale en ningún evento.
- La **referencia del cliente** (`PO-2024-0098`) no alimenta ninguna decisión. Fuera.
- Los **mensajes de error** pueden contener lo que el usuario tecleó (o el nombre de un candidato del
  Talent Pipeline). Se envían solo el tipo de error y una huella (hash).
- Las **rutas** se reducen a plantilla: `/talent/records/[id]`, nunca el id real.
- En `login_failed` hace falta agrupar intentos por cuenta y por origen para detectar ataques. El email
  y la IP salen como **HMAC**; la IP, además, con una sal que cambia cada día, para que no se pueda
  seguir a nadie de un día a otro.

---

## 7. Fase 3 — Stream o batch, y cómo frenar los eventos ruidosos

### 7.1 El criterio

Para cada evento se hizo la misma pregunta: **¿hay alguien que tenga que actuar antes del siguiente
lote?** Salieron **7 eventos en stream**:

| Evento | Quién actúa en minutos y para qué |
|---|---|
| `outbound_order_created` | Ana ve que el ritmo de despacho cae antes de incumplir el SLA |
| `stock_threshold_triggered` | Miguel avisa al cliente antes del quiebre |
| `outbound_order_rejected` | Hay un pedido parado en el muelle: conteo inmediato |
| `login_failed` | Un ataque prueba cientos de contraseñas en minutos |
| `database_connection_failed` | Sin base de datos no se registra nada en ningún almacén |
| `api_error_occurred` | Un despliegue roto se revierte en minutos |
| `password_reset_email_failed` | Un operario sin acceso no puede trabajar en su turno |

Y algunos que **parecen** urgentes pero no lo son:

- `direct_stock_edit_rejected` es obligatorio y suena grave, pero el sistema **ya** rechazó el cambio:
  el stock no se ha tocado. La decisión (formar o ajustar permisos) se toma en la revisión semanal.
  → batch diario.
- `inbound_order_created`: la capacidad se planifica por turno. → batch horario.

Un detalle que salió del análisis y simplifica mucho la captura: **ningún evento del navegador
necesita stream**. Todo lo urgente lo emite la API.

### 7.2 Throttle y debounce

La tabla completa está en la sección 6.3 del plan. Los dos casos más didácticos:

- **`api_latency_recorded`**: un evento por petición multiplicaría el volumen por el tráfico. Se
  **agrega**: un evento por ruta, método y clase de estado cada minuto, con p50, p95 y máximo. Da igual
  que haya 10 o 10.000 peticiones: como mucho ~80 eventos por minuto.
- **`stock_threshold_triggered`**: si el stock está en 3 con un mínimo de 5, cada nueva salida seguiría
  "por debajo". Se usa **disparo por flanco**: el evento sale solo al **cruzar** el mínimo, y no vuelve a
  salir hasta que una entrada lo devuelva por encima (se "rearma"). Un cruce, una alerta.

### 7.3 Cómo viajan los eventos

- Los eventos de negocio se emiten **después del `commit`**. Si la transacción falla, no hay evento: la
  telemetría nunca dice que hubo un despacho que la base de datos no tiene.
- La telemetría **nunca rompe la operación**: si el destino no responde, se reintenta o se escribe en
  el log, pero el despacho se registra igual.
- El navegador junta sus eventos en una cola y los envía cada 5 minutos, o con `sendBeacon` al cerrar la
  pestaña (una petición que el navegador garantiza aunque la página se esté cerrando).

---

## 8. Riesgos y exclusiones: lo que se decidió NO medir

Esta sección es la que mejor demuestra criterio, porque descartar requiere una razón. Algunos ejemplos
(la lista completa está en la sección 7 del plan):

| Descartado | Por qué |
|---|---|
| Consultas de un SKU | No completa la frase: ninguna decisión cambia por saber cuántas veces se mira un SKU. |
| `stock_threshold_cleared` | Se puede **deducir** de las entradas y el umbral; emitirlo duplicaría la señal. |
| Pérdidas dentro de `outbound_order_created` | Mezclaría despachos con mermas y falsearía el ritmo y el SLA. Por eso existe `stock_loss_recorded`. |
| Teclas, foco, scroll, mapas de calor | Mucho volumen, ninguna hipótesis concreta y riesgo de capturar lo que hay en pantalla. |
| Eventos de negocio del Talent Pipeline | Maneja datos personales de candidatos y queda fuera del BRIEFING. Solo navegación, rendimiento y errores. |
| Almacén del usuario en los eventos de sesión | Los usuarios no tienen almacén asignado: inventarlo sería meter un dato falso. |

Y los riesgos, cada uno con su mitigación: renombrar un cliente cambia su slug, los reintentos duplican
eventos, los relojes de los navegadores no son fiables, dos salidas simultáneas podrían disparar el
umbral dos veces (no pueden: `register_exit` bloquea la fila del SKU), etc.

---

## 9. Cómo se construyeron el plan y el JSON sin que se contradigan

El catálogo aparece **dos veces**: en tablas Markdown (para personas) y en JSON Schema (para
máquinas). Con 26 eventos y 146 propiedades, escribirlo dos veces a mano garantizaba
contradicciones.

Por eso se escribió **una sola vez**, como datos en un script de Python, y el script generó a la vez
`event-schemas.json` y las secciones del catálogo del plan (fichas, frases, clasificación y tabla de
entrega). El texto explicativo del plan se escribió a mano alrededor.

Ese script fue una herramienta de trabajo y **no está en el repositorio**. Desde ahora, la garantía de
que los dos archivos coinciden la da el **test** (sección 11): si alguien cambia la entrega de un evento
en el JSON y no en el plan, o añade un evento solo en uno de los dos, el test falla.

---

## 10. Problemas que aparecieron y cómo se resolvieron

### 10.1 La copia del proyecto no tenía el inventario

El CONTEXT-10 llegó en la carpeta "Copia Proyecto", que no tiene el backend ni las pantallas de
inventario. Se trabajó en el proyecto principal (sección 3).

### 10.2 Dos métricas obligatorias no se pueden medir todavía

Ver sección 5. La tentación era inventarse un disparador "aproximado". Se prefirió documentar los
prerrequisitos (PR-1, PR-2) con el diseño exacto de lo que falta.

### 10.3 `array<enum>` desaparecía en GitHub

Las tablas del catálogo describían las listas como `array<enum>`. GitHub interpreta `<enum>` como una
etiqueta HTML y la borra, así que se veía solo `array`. Se cambió a `array[enum]`.

### 10.4 El enlace al BRIEFING no funcionaría en GitHub

La carpeta `audit/` está en el `.gitignore`, así que el CONTEXT-10 copiado allí no se sube. El plan lo
cita como ruta en texto (no como enlace) y reproduce sus tablas literalmente en la sección 2.1.

### 10.5 El test miraba un nivel por encima

El primer test fallaba en 3 casos con `KeyError: 'product_category'`. En el JSON, la allowlist está
anidada tres niveles: `properties` (del envelope) → `properties` (el objeto payload) → `properties`
(las claves permitidas). La función auxiliar `allowlist()` se quedaba en el segundo. Corregida, pasaron
los 72.

### 10.6 El Hito 13 movió las líneas de referencia

El arreglo del N+1 del Hito 13 añadió una línea en `services/inventory_service.py`, y las referencias
del plan (`:120`, `:134`, `:146`, `:150`) pasaron a apuntar una línea antes de lo debido. Se
actualizaron a `:121`, `:135`, `:147` y `:151` en el plan y en el JSON. Es el precio de dar referencias
tan precisas: hay que revisarlas cuando cambia el código. La alternativa (nombrar solo la función)
es más estable, y por eso cada disparador cita **las dos cosas**: la función y la línea.

### 10.7 Lo que el Hito 13 cambia para la telemetría

- El `timing_middleware` del Hito 13 ya cronometra cada petición: es el sitio natural donde la captura
  colgará la agregación de `api_latency_recorded`. Pero hoy registra `request.url.path`, que es la ruta
  **real** (`/inventory/products/41`); para el evento hay que usar la **plantilla**
  (`request.scope["route"].path` → `/inventory/products/{sku_id}`), o cada SKU sería una "ruta" distinta.
- Con la caché, el p95 de `GET /inventory/products` mezclará aciertos (~10 ms) y fallos (~440 ms).
  Para interpretar `api_latency_recorded` habrá que tenerlo en cuenta; si hiciera falta separarlos, se
  añadiría una propiedad opcional `cache_status` (cambio menor, `1.1.0`).

---

## 11. Cómo se comprobó

| Comprobación | Resultado |
|---|---|
| `uv run pytest tests/telemetry` | **72 / 72** |
| Suite completa (`uv run pytest`) | **872 / 872** |
| `Draft7Validator.check_schema` sobre `event-schemas.json` | Esquema draft-07 válido |

Qué comprueba el test, en lenguaje llano:

- **Que el JSON es un JSON Schema válido** y que cada evento está enlazado desde la raíz.
- **El envelope**: que exige los 8 campos del checklist, que no admite claves de más, que rechaza un
  `timestamp` que no es ISO 8601, un `eventId` que no es UUID, un `event_type` en `camelCase` o un
  email en `userId`.
- **Las allowlists**: que todas son cerradas, que todas las propiedades tienen tipo y descripción,
  que ninguna se llama `tracking_number`, `email`, `reference`… y que un evento con `tracking_number`
  se **rechaza**.
- **El catálogo**: que los 5 obligatorios están y llevan los campos mínimos, que hay al menos 8
  oportunidades en 3 categorías, que todos los nombres siguen `entidad_acción` y que cada evento tiene
  hipótesis, decisión, disparador, entrega justificada y PII documentada.
- **Coherencia con el código**: que las categorías del JSON son las de `services/models.py`, que los
  roles son los de `UserRole`, etc. Si mañana se añade una categoría al inventario, el test avisa.
- **Coherencia con el plan**: que el Markdown y el JSON listan los mismos eventos y la misma decisión
  stream/batch.

---

## 12. Decisiones discutibles (y cómo defenderlas)

Si alguien pregunta "¿por qué así?", estas son las respuestas:

- **"¿Por qué `client_id` es un slug y no un número?"** Porque no existe ninguna entidad cliente con id.
  Inventar un número sería peor: no se podría reproducir. El slug es determinista y está documentado
  como provisional (PR-4), con su cambio de versión previsto.
- **"¿Por qué `direct_stock_edit_rejected` no va en stream si es obligatorio?"** Obligatorio no significa
  urgente. El cambio ya se rechazó; la decisión es de formación y se toma cada semana.
- **"¿Por qué tantos eventos de error y autenticación si el BRIEFING habla de inventario?"** Porque el
  enunciado pide explorar el backoffice entero, y porque una sesión caducada o una base de datos caída
  **son** problemas de inventario: impiden registrar movimientos.
- **"¿No es exagerado medir el abandono de formularios?"** Cada movimiento físico que no se registra es
  una discrepancia futura. Cruzar abandonos con discrepancias por almacén es justo el tipo de pregunta
  que Ana necesita.
- **"¿Por qué el navegador no puede mandar el `userId`?"** Porque no es de fiar: lo pone el servidor a
  partir del JWT. Incluso en `session_expired` (con el token caducado), el servidor comprueba la firma
  del token ignorando solo la fecha de caducidad.

---

## 13. El siguiente paso: la captura

El plan termina con una guía (sección 8 de `TELEMETRY_PLAN.md`) pensada para que otra persona
instrumente sin preguntar. El orden es:

1. Ids de correlación (PR-3).
2. Emisor de backend `services/telemetry/emitter.py`, que valida contra `event-schemas.json` y lee
   del propio esquema si el evento es stream o batch (así esa decisión no se duplica en el código).
3. Los eventos de inventario que ya se pueden emitir.
4. Umbrales y conteos (PR-1, PR-2).
5. Autenticación y errores de backend.
6. Ingesta y emisor del navegador.
7. Eventos del navegador.
8. Seed ampliado (PR-6).

Y un criterio de aceptación por evento: un test que provoque el disparador y compruebe que sale
**exactamente un** evento, válido y sin claves fuera de la allowlist.

---

## 14. Archivos creados y modificados

| Archivo | Cambio |
|---|---|
| `TELEMETRY_PLAN.md` | **Nuevo.** Plan de Telemetría completo |
| `event-schemas.json` | **Nuevo.** Esquemas JSON Schema draft-07 de los 26 eventos y del envelope |
| `tests/telemetry/test_event_schemas.py` | **Nuevo.** 72 tests de validez y coherencia |
| `pyproject.toml`, `uv.lock` | Dependencia de desarrollo `jsonschema` |
| `audit/CONTEXTS/CONTEXT-10-trackflow.es.md` | Copiado desde la copia del proyecto (local; `audit/` no se sube) |
| `TELEMETRY_PLAN.md`, `event-schemas.json` | Líneas de referencia actualizadas tras el Hito 13 |
| `hito_14.md` | **Nuevo.** Este documento |

No se ha tocado código de la aplicación: este hito es solo el plan.

---

## 15. Lo que deberías poder explicar después de leer esto

1. La diferencia entre **log, evento y métrica**, y por qué un evento necesita una forma fija.
2. Por qué cada evento necesita una **hipótesis y una decisión**, y qué se hace con los que no la tienen.
3. Para qué sirve cada campo del **envelope**, y por qué el `userId` lo pone el servidor.
4. Por qué una **allowlist** protege mejor que una blocklist.
5. La diferencia entre **anonimizar y seudonimizar**, y por qué se usa **HMAC** y no un hash simple.
6. Cómo se decide **stream o batch** (urgencia de la decisión, no gusto técnico), con un ejemplo de
   evento obligatorio que va en batch.
7. Qué son **throttle, debounce, deduplicación, agregación y muestreo**, y qué es el **disparo por flanco**.
8. Por qué los eventos de negocio se emiten **después del `commit`**.
9. Por qué es mejor documentar un **prerrequisito** que inventarse un disparador aproximado.
10. Cómo se evita que el plan y el JSON **se contradigan** con el tiempo.

---

## 16. Glosario

| Término | Significado |
|---|---|
| **Telemetría** | Que el sistema envíe eventos sobre lo que pasa mientras se usa |
| **Evento** | Mensaje estructurado que describe un hecho, con forma fija |
| **Event Envelope** | Campos comunes a todos los eventos (id, fecha, sesión, usuario, tipo, versión, petición) |
| **`properties`** | La parte específica de cada evento, dentro del envelope |
| **Allowlist** | Lista cerrada de claves permitidas; todo lo demás se rechaza |
| **Taxonomía `entidad_acción`** | Regla de nombres: entidad primero, verbo en participio al final |
| **JSON Schema (draft-07)** | Formato estándar para describir y validar la forma de un JSON |
| **`additionalProperties: false`** | Regla de JSON Schema que prohíbe claves no declaradas |
| **SemVer** | Versionado `mayor.menor.parche`: menor = compatible, mayor = rompe |
| **PII** | Dato que identifica a una persona (email, nombre, IP…) |
| **Seudonimizar** | Sustituir un dato personal por un código que solo se deshace con información guardada aparte |
| **HMAC** | Huella de un dato calculada con una clave secreta; sin la clave no se puede adivinar el original |
| **Sal** | Valor que se mezcla con el dato antes de calcular la huella; si cambia, cambian todas las huellas |
| **RGPD** | Reglamento europeo de protección de datos (aplica a Zaragoza) |
| **Stream** | Entrega en tiempo real, evento a evento |
| **Batch** | Entrega por lotes, cada cierto tiempo |
| **Throttle** | Limitar a N eventos por intervalo |
| **Debounce** | Esperar a que algo deje de cambiar antes de emitir |
| **Agregación** | Enviar un resumen (conteo, percentiles) en vez de cada caso |
| **Muestreo** | Enviar solo un porcentaje de los eventos |
| **Disparo por flanco** | Emitir al cruzar un límite, no mientras se está al otro lado |
| **Idempotencia** | Que repetir una operación no cambie el resultado; aquí, gracias a `eventId` |
| **Correlación** | Unir eventos, peticiones y logs del mismo hecho mediante ids compartidos (`requestId`, `sessionId`) |
| **Ingesta** | El punto que recibe, valida y guarda los eventos |
| **`sendBeacon`** | API del navegador que envía datos aunque la página se esté cerrando |
| **p50 / p95** | Mediana / valor por debajo del cual queda el 95 % de las mediciones |
| **Core Web Vitals** | LCP, INP y CLS: métricas de experiencia de carga e interacción |
| **Fingerprint** | Hash que agrupa errores iguales sin enviar su mensaje |
| **SLA** | Compromiso de nivel de servicio (p. ej. plazo de entrega) con el cliente |
| **Commit** | Momento en que una transacción queda guardada definitivamente en la base de datos |
