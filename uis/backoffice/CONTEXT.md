# Talent Pipeline Tracker — context.md

> Versión optimizada del contexto que diste. Reorganiza el mismo contenido con el vocabulario estructural del curso (Rol/Stack/Restricciones/Contenido, Modelo de Caja, Método de Tres Pasos) para que el agente de código tenga menos que adivinar. **No cambia ni una sola especificación tuya** — solo las separa, las ordena y llena los huecos que encontré (marcados explícitamente en la sección 10, no los he decidido por ti).

## 0. Propósito

**Usuario:** personal del equipo de People & Talent gestionando una campaña de selección activa con más de 100 candidaturas.

**Qué intenta hacer:** revisar candidaturas recibidas, filtrarlas por estado/etapa/nombre, abrir el detalle de una candidatura concreta para actualizar su estado o etapa con una sola interacción, y dejar notas internas de seguimiento — todo contra la API real del Talent Tracker (sección 4).

**Páginas de la interfaz:**
- **Home / Listado** (`/`) — candidaturas filtradas, con navegación de filtros a la izquierda.
- **Detalle de candidatura** (`/records/[id]`) — ficha completa de un candidato + sus notas.

## 1. Rol

Eres un desarrollador senior encargado de elaborar esta web.

## 2. Stack

- **Next.js (App Router) + React + TypeScript.**
- **Sin librerías externas de gestión de estado** (Redux, Zustand, Jotai, etc.) — el estado a nivel de componente con hooks nativos es suficiente para este hito.

## 3. Restricciones

- **Diseño heredado, no rediseñado:** el header (logo "Trackflow" centrado, enlace a Home) debe reutilizar tal cual el mismo diseño de la página ya construida en `uis/website/trackflow-web` de este mismo repositorio — no crear un header nuevo, adaptar el existente.
- **Cambio de estado/etapa vía `PATCH`, nunca `PUT`:** el detalle permite cambiar `status` y `stage` con una sola interacción (ej. un select) — eso se guarda con `PATCH /records/{id}` (body `{ status?, stage? }`). No uses `PUT` para esto: `PUT` reemplaza el registro completo y exige reenviar `full_name`/`email`/`phone`/`position`/`experience_years`, arriesgando perder datos si falta alguno.
- **Estados de carga y errores obligatorios:** cada llamada a la API (listar, cargar detalle, guardar cambio de estado/etapa, añadir/eliminar nota) debe comunicar visualmente que está en curso (ej. skeleton o spinner) y manejar con claridad los casos de error — comprobando `response.ok`/`response.status`, ya que `fetch()` no lanza excepción en un 404 o un 422.
- **Filtros reflejados en la URL:** los filtros activos (`status`, `stage`, `search`) y la página actual deben vivir como query params en la URL (`useSearchParams`/`usePathname`), no solo en estado local — así la vista es compartible/recargable sin perder el filtro aplicado.
- **La foto de perfil no es parte de la API:** el JSON de un candidato no incluye ninguna foto. Por defecto, todas las tarjetas usan `uis/talent-pipeline-tracker/imagenesPerfil/imagenPerfil.png`. La función de "Añadir foto de perfil" es una funcionalidad local del proyecto, no de la API del Talent Tracker — como un Client Component no puede escribir directamente en el sistema de archivos, necesita un **Route Handler de Next.js** (`app/api/upload-photo/route.ts`) que reciba el archivo subido y lo guarde en `uis/talent-pipeline-tracker/imagenesPerfil/`, devolviendo la ruta para que la vista se actualice. (Ver también el punto sin resolver en la sección 10 sobre cómo se nombra/asocia cada foto a su candidato.)

## 4. Conexión con la API

- **Base URL:** `https://playground.4geeks.com/tracker/api/v1` — todas las rutas de este documento son relativas a esta base.
- **Sin autenticación:** no hay `securityScheme` ni cabecera `Authorization` en ningún endpoint — no construyas lógica de login, no aplica a este proyecto.
- **Formato:** JSON en todas las solicitudes y respuestas. En POST/PUT/PATCH, cabecera `Content-Type: application/json`.

## 5. Endpoints disponibles

### Recurso: candidaturas (`Records`)

| Método | Ruta | Para qué sirve | Body / Params |
|---|---|---|---|
| `GET` | `/records` | Listar candidaturas, con filtros y paginación | Query params: `status`, `stage`, `search`, `page`, `limit` (todos opcionales) |
| `POST` | `/records` | Crear una nueva candidatura | Body: ver **RecordCreate** (sección 8) |
| `GET` | `/records/{id}` | Detalle de una candidatura | — |
| `PUT` | `/records/{id}` | Reemplazar una candidatura **completa** | Body: ver **RecordCreate** |
| `PATCH` | `/records/{id}` | Cambiar solo `status` y/o `stage` | Body: `{ status?, stage? }` |
| `DELETE` | `/records/{id}` | Eliminar una candidatura | — |

### Recurso: notas internas (`Notes`), anidado bajo una candidatura

| Método | Ruta | Para qué sirve | Body / Params |
|---|---|---|---|
| `GET` | `/records/{id}/notes` | Listar las notas de una candidatura | — |
| `POST` | `/records/{id}/notes` | Añadir una nota | Body: `{ content: string }` |
| `DELETE` | `/records/{id}/notes/{note_id}` | Eliminar una nota concreta | — |

## 6. Valores válidos (enums) para `status` y `stage`

- **`status`**: `received` · `in_progress` · `selected` · `discarded`
- **`stage`**: `pending` · `review` · `personal_interview` · `technical_interview` · `offer_presented`

Estos son los únicos valores a mostrar en los selects de filtro y de edición.

## 7. Forma real de las respuestas (verificado con llamadas reales — el spec de Swagger las deja sin documentar)

**`GET /records` → objeto envoltorio con paginación**, y cada candidato **incluye sus notas embebidas**:
```json
{
  "total": 100, "page": 1, "limit": 2,
  "data": [
    {
      "id": "53f2bbdc-...", "full_name": "Michael Smith", "email": "...", "phone": "...",
      "position": "Jefa/e de Gabinete", "linkedin_url": "https://linkedin.com/in/...",
      "cv_url": "https://storage.example.com/cv/....pdf", "status": "in_progress", "stage": "review",
      "experience_years": 6, "applied_at": "2026-02-28T20:04:32.114Z", "updated_at": "2026-03-27T20:04:32.114Z",
      "notes": [{ "id": "...", "record_id": "...", "content": "...", "created_at": "..." }],
      "notes_count": 1
    }
  ]
}
```

**`GET /records/{id}` → objeto plano, SIN notas embebidas** (solo `notes_count`) — asimetría importante con el listado:
```json
{
  "id": "53f2bbdc-...", "full_name": "Michael Smith", "email": "...", "phone": "...",
  "position": "Jefa/e de Gabinete", "linkedin_url": "...", "cv_url": "...",
  "status": "in_progress", "stage": "review", "experience_years": 6, "notes_count": 1,
  "applied_at": "2026-02-28T20:04:32.114Z", "updated_at": "2026-03-27T20:04:32.114Z"
}
```
Para mostrar las notas en el detalle hay que pedirlas aparte con `GET /records/{id}/notes`, que responde:
```json
{ "data": [{ "id": "...", "record_id": "...", "content": "...", "created_at": "..." }], "meta": { "total": 1 } }
```

Campos de una nota: `id`, `record_id`, `content`, `created_at`.

## 8. Estructura y contenido — Vista Listado (Home, `/`)

**Estructura general (contenedor exterior):** página de ancho completo con un header fijo arriba (heredado de `trackflow-web`, logo "Trackflow" centrado, enlace a `/`) y, debajo, un cuerpo dividido en dos: un `<nav>` de filtros a la izquierda y un `<main>` con el listado a la derecha.

**Nav de filtros (izquierda) — contenido:**
- Filtro por `status` (los 4 valores de la sección 6).
- Filtro por `stage` (los 5 valores de la sección 6).
- Campo de búsqueda (`search`, filtra por `full_name` o `email` a la vez, del lado del servidor).
- Los tres, reflejados como query params en la URL (Restricción de la sección 3) y enviados tal cual a `GET /records`.

**Main — listado de candidatos (uno por candidatura, tarjeta/fila):**

| Elemento | Campo API | Notas de presentación |
|---|---|---|
| Foto de perfil | *(no viene en la API)* | Cuadrado pequeño; por defecto `imagenPerfil.png` (sección 3) |
| Nombre completo | `full_name` | Junto a la foto, tamaño principal |
| Posición | `position` | Debajo del nombre, tamaño menor |
| Etiqueta de estado | `status` | Traducir a etiqueta legible (ej. `in_progress` → "En proceso") |
| Etiqueta de etapa | `stage` | Traducir a etiqueta legible |
| Etiqueta de experiencia | `experience_years` | Ej. "6 años de experiencia" |

Al pulsar una candidatura, navega al detalle (`/records/{id}`).

## 9. Estructura y contenido — Vista Detalle (`/records/[id]`)

**Estructura general:** mismo header fijo arriba (funcional, vuelve a `/`). Debajo, centrada, una tarjeta con: la foto (más grande) y, al lado, el resto de los campos apilados uno encima de otro. Debajo de la tarjeta, la sección de notas.

**Foto de perfil (dentro de la tarjeta):**
- Foto en tamaño grande.
- Botón superpuesto en la esquina superior derecha de la foto, oculto por defecto, visible solo con el cursor encima (`:hover`), con el texto "Añadir foto de perfil".
- Al pulsarlo, permite elegir un archivo y lo sube al Route Handler descrito en la sección 3.

**Datos del candidato (al lado de la foto, uno encima de otro):**

| Campo | Origen | Editable? |
|---|---|---|
| `full_name` | Nombre | No |
| `email` | — | No |
| `phone` | — | No |
| `position` | — | No |
| `linkedin_url` | Puede ser `null` — mostrar solo si existe, como enlace | No |
| `cv_url` | Puede ser `null` — mostrar solo si existe, como enlace de descarga/apertura | No |
| `experience_years` | — | No |
| `status` | Select con los 4 valores de la sección 6 | Sí — guarda con `PATCH` (sección 3) |
| `stage` | Select con los 5 valores de la sección 6 | Sí — guarda con `PATCH` |
| `applied_at` | Fecha de postulación | No |
| `updated_at` | Última actualización | No |

**Sección de notas (debajo de la tarjeta):**
- Un campo de texto para escribir una nota nueva; al enviarla, `POST /records/{id}/notes` con `{ content }`.
- Debajo, las notas ya escritas (`GET /records/{id}/notes`), presentadas de **dos en dos** (rejilla de 2 columnas), cada una en una tarjeta de **tamaño fijo de tres renglones** (el texto que exceda esas tres líneas se trunca/oculta), con una barra de scroll a la derecha del conjunto para ver el resto de notas.
- Cada nota debe poder eliminarse (`DELETE /records/{id}/notes/{note_id}`).

## 10. Sin especificar en el brief original — necesitan una decisión ⚠️

Esto **no lo he decidido por ti** — son huecos reales del contexto que diste, y el agente de código va a necesitar una respuesta para alguno de ellos tarde o temprano:

1. **Crear una candidatura nueva** (`POST /records`, ya documentado en la sección 5) — el brief no dice **dónde** vive este flujo en la interfaz (¿un botón en el header? ¿en el nav de filtros? ¿una página aparte?). Sin esto, la interfaz solo cubre lectura y actualización, no creación.
2. **Eliminar una candidatura** (`DELETE /records/{id}`) — tampoco aparece en ningún punto de la interfaz descrita.
3. **Nombrado de las fotos subidas**: para que cada candidato recupere su propia foto (y no la del último que se subió), hace falta un criterio de nombrado — la opción más simple es nombrar el archivo con el `id` del candidato (ej. `{id}.png`), pero esto es una propuesta mía, no algo que hayas especificado — confírmalo o cámbialo antes de pasarlo al agente.

## Fuente

Base: contexto y especificaciones de API que ya tenías escritos. Reorganizado con el vocabulario del curso (Rol/Stack/Restricciones/Contenido, Modelo de Caja, Método de Tres Pasos) de `005.Frontend development with Coding Agents/001.Dar especificaciones visuales a la IA`.