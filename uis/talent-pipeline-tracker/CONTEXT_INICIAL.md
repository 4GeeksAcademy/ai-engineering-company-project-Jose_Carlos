# Talent Pipeline Tracker

La finalidad de esta interfaz gráfica es comunicarse y gestionar las más de 100 canditaturas que se han recibido en el proceso de selección activa de personal que se ha abierto. Estas canditaturas se han gestionado mediante una API a la que nos conectaremos y haremos los cambios. La interfaz se divide en dos principalmente, la parte donde se muestra la lista de candidatos filtrados según los criterios que ahora expondré y una vista de canditatura individual de cada candidato. 

# Rol

Eres un desarrollador senior encargado de elaborar la web. Usa únicamente Next.js (App Router), React y TypeScript. No uses librerías externas de gestión de estado (Redux, Zustand, Jotai, etc.). El estado a nivel de componente con hooks es suficiente para este hito.

# Estructura

La página principal se compone un header fijo arriba con el nombre de la empresa "Trackflow" en el centro, con el mismo diseño que la página creada en /workspaces/ai-engineering-company-project-Jose_Carlos/uis/website/trackflow-web. Este botón vuelve a la página principal cuando lo pulsamos. La página principal se va a dividir en dos; a la izquierda un nav con todos los filtros que hay que implementar, y a la derecha el main con el listado de los candidatos. El elemento que muestra cada candidato en la lista tiene un pequeño cuadrado para la foto de perfil (Como en el json no viene tendrán todas por defecto la imagen uis/talent-pipeline-tracker/imagenesPerfil/imagenPerfil.png), junto a la foto vemos el nombre completo del candidato, abajo algo más pequeño la posición que ocupa y a modo de etiquetas el status, el stage y los años de experiencia

Cuando pulsamos cada canditatura nos lleva a una vista diferente, con el mismo header arriba, funcional para volver a la página principal de la interfaz. Abajo y centrado, una tarjeta con los datos del candidato. La foto aparece más grande y en su esquina superior derecha tiene un botón que solo aparece cuando pasamos por encima de la foto, y que pone "Añadir foto de perfil". Este botón es funcional y nos deja cambiar la foto y poner la que queramos (En ppio se guardarán en uis/talent-pipeline-tracker/imagenesPerfil al no ser muchas y ser algo que implemento por gusto). El resto de los datos (más adelante especifico cuales son los campos a hacer) vienen al lado de la foto, uno encima del otro. Abajo de la tarjeta hay un espacio para escribir notas, una parte importante de la interfaz. Debajo de este espacio vienen las notas ya escritas, se presentan de dos en dos en tamaño fijo de tres renglones, y se escrolea con una barra de scroll situada a su derecha.


## 1. Conexión con la API
 
- **Base URL:** `https://playground.4geeks.com/tracker/api/v1`
  - Todas las rutas de este documento son relativas a esa base. Por ejemplo, "GET /records" significa `GET https://playground.4geeks.com/tracker/api/v1/records`.
  - **Formato:** JSON en todas las solicitudes y respuestas. En POST/PUT/PATCH, cabecera `Content-Type: application/json`.

## 2. Endpoints disponibles
 
### Recurso: candidaturas (`Records`)
 
| Método | Ruta | Para qué sirve | Body / Params |
|---|---|---|---|
| `GET` | `/records` | Listar candidaturas, con filtros y paginación | Query params: `status`, `stage`, `search`, `page`, `limit` (todos opcionales) |
| `POST` | `/records` | Crear una nueva candidatura | Body: ver **RecordCreate** (sección 4) |
| `GET` | `/records/{id}` | Detalle de una candidatura | — |
| `PUT` | `/records/{id}` | Reemplazar una candidatura **completa** | Body: ver **RecordCreate** (mismos campos que crear) |
| `PATCH` | `/records/{id}` | Cambiar solo `status` y/o `stage` | Body: `{ status?, stage? }` |
| `DELETE` | `/records/{id}` | Eliminar una candidatura | — |
 
### Recurso: notas internas (`Notes`), anidado bajo una candidatura
 
| Método | Ruta | Para qué sirve | Body / Params |
|---|---|---|---|
| `GET` | `/records/{id}/notes` | Listar las notas de una candidatura | — |
| `POST` | `/records/{id}/notes` | Añadir una nota | Body: `{ content: string }` |
| `DELETE` | `/records/{id}/notes/{note_id}` | Eliminar una nota concreta | — |
 
## 3. Valores válidos (enums) para `status` y `stage`
 
Estos valores están documentados solo como texto libre en la descripción del parámetro de filtro — no hay una validación de tipo enum en el spec, así que trátalos como las únicas opciones "oficiales" a mostrar en tus selects/dropdowns:
 
- **`status`**: `received` · `in_progress` · `selected` · `discarded`
- **`stage`**: `pending` · `review` · `personal_interview` · `technical_interview` · `offer_presented`

## 5. Campos que debe presentar la interfaz — por vista
 
### Vista Listado (`/records`, con filtros)
De un vistazo, según pide el brief del proyecto: **nombre, puesto, estado, etapa**.
 
| Campo | Origen | Obligatorio en la vista |
|---|---|---|
| `full_name` | Nombre del candidato | Sí |
| `position` | Puesto al que aplica | Sí |
| `status` | Estado actual (traducir el valor a una etiqueta legible, ej. `in_progress` → "En proceso") | Sí |
| `stage` | Etapa actual del pipeline (igual, traducir a etiqueta legible) | Sí |
| `applied_at` | Fecha de postulación | Recomendado (útil para ordenar) |
| `notes_count` | Nº de notas | Opcional (indicador rápido de seguimiento) |
 
### Vista Detalle (`/records/{id}` + `/records/{id}/notes`)
Todo el candidato, más sus notas:
 
| Campo | Notas de presentación |
|---|---|
| `full_name` | Título de la vista |
| `email` | — |
| `phone` | — |
| `position` | — |
| `linkedin_url` | Puede ser `null` — mostrar solo si existe; renderizar como enlace |
| `cv_url` | Puede ser `null` — mostrar solo si existe; enlace de descarga/apertura |
| `experience_years` | — |
| `status` | Editable — select con los 4 valores de la sección 3, guarda con `PATCH` |
| `stage` | Editable — select con los 5 valores de la sección 3, guarda con `PATCH` |
| `applied_at` | Fecha de postulación (solo lectura) |
| `updated_at` | Última actualización (solo lectura) |
| **Notas** (`GET /records/{id}/notes`) | Lista de `content` + `created_at`; formulario para añadir (`POST`, solo campo `content`); botón eliminar por nota (`DELETE .../notes/{note_id}`) |
 
### Formulario de alta (crear candidatura — `POST /records`)
Campos de `RecordCreate`:
 
| Campo | Tipo | ¿Obligatorio? |
|---|---|---|
| `full_name` | texto | Sí |
| `email` | texto (formato email) | Sí |
| `phone` | texto | Sí |
| `position` | texto | Sí |
| `experience_years` | número | Sí |
| `linkedin_url` | texto (URL) | No — puede omitirse/quedar `null` |
| `cv_url` | texto (URL) | No — puede omitirse/quedar `null` |
 
`status` y `stage` **no se envían al crear** — no forman parte de `RecordCreate`; la API los asigna por defecto (probablemente `received`/`pending` — verifícalo creando un registro de prueba).
 
### Edición completa (`PUT /records/{id}`) vs. cambio rápido de estado/etapa (`PATCH /records/{id}`)
- **`PUT`** reemplaza el registro **entero**: exige de nuevo `full_name`, `email`, `phone`, `position`, `experience_years` (y acepta `linkedin_url`/`cv_url`). Si tu formulario de edición completa envía un PUT, tiene que reenviar **todos** los campos, aunque el usuario no haya tocado algunos — si omites uno, corres el riesgo de perder ese dato en el servidor (es el mismo antipatrón de PUT vs. PATCH que ya viste en el módulo de arquitectura web).
- **`PATCH`** es la vía correcta para lo que pide el brief — "cambiar su estado o etapa con una sola interacción" — porque solo toca esos dos campos sin arriesgar el resto del registro.
## 6. Puntos a tener en cuenta al escribir el código
 
- Los filtros de `GET /records` (`status`, `stage`, `search`, `page`, `limit`) son **del lado del servidor** — no hace falta filtrar tú mismo en el cliente: basta con reflejar los filtros activos como query params en la URL (tal como se enseñó con `useSearchParams`/`usePathname`).
- `search` busca por `full_name` **o** `email` a la vez.
- `linkedin_url` y `cv_url` pueden llegar como `null` — la interfaz debe comprobar su existencia antes de renderizar el enlace, para no mostrar un enlace roto.
- Recuerda comprobar `response.ok`/`response.status` en cada llamada — esta API, como cualquier otra, puede devolver 404 (candidatura inexistente) o 422 (validación fallida, ej. un email mal formado) sin que `fetch()` lo trate como error de red.
- No hay endpoint de autenticación: no construyas lógica de login para este proyecto — no aplica.


