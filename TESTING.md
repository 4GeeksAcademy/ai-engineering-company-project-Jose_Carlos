# TESTING

Pruebas unitarias de la API (FastAPI + pytest) y de la lógica de autenticación del frontend
(TypeScript + Jest).

- **AUTH-088** — autenticación: `tests/auth/` y `uis/talent-pipeline-tracker/__tests__/`.
- **API-042** — backoffice: incidencias (`tests/incidents/`) y proveedores (`tests/suppliers/`).
- **FE-019** — utilidades del frontend: `uis/talent-pipeline-tracker/__tests__/`.

## Cómo ejecutar

### Backend (pytest)

Desde la raíz del repositorio:

```bash
uv sync                # instala dependencias, incluido el grupo dev (pytest, pytest-cov)
uv run pytest          # toda la batería
uv run pytest tests/auth          # solo las unitarias de autenticación (AUTH-088)
uv run pytest tests/incidents tests/suppliers   # solo las del backoffice (API-042)
uv run pytest --cov               # con cobertura de services/api (configurada en pyproject.toml)
```

No hace falta `.env` ni servidor levantado: `tests/conftest.py` fija una clave JWT de
pruebas, apunta TinyDB a un directorio temporal, desactiva el envío real de correos y usa
embeddings por hashing (no se descarga ningún modelo).

### Frontend (Jest)

Los tests del frontend son independientes del backend: no necesitan la API levantada, ni
`uv`, ni `.env` (`fetch` está sustituido por un mock). Basta con Node.js.

Desde `uis/talent-pipeline-tracker/`:

```bash
npm install            # solo la primera vez
npm test               # toda la batería de Jest
npx jest --coverage    # con cobertura de app/lib (o: npm run test:coverage)
```

Para ejecutar solo una parte:

```bash
npx jest __tests__/api.test.ts         # un archivo
npx jest __tests__/constants.test.ts
npx jest __tests__/auth.test.ts
npx jest -t "formatDate"               # solo los tests cuyo nombre contiene ese texto
npx jest --watch                       # relanza al guardar (necesita un repositorio git)
```

Desde la raíz del repositorio, sin cambiar de directorio:

```bash
npm --prefix uis/talent-pipeline-tracker test
```

Los archivos de prueba viven en `uis/talent-pipeline-tracker/__tests__/` y la configuración
en `uis/talent-pipeline-tracker/jest.config.ts`.

## Qué cubre cada suite

| Suite | Qué prueba |
| --- | --- |
| `tests/auth/test_register.py` | `POST /users`: `register_user`, `UserCreate`, `user_service.create_user`, hash de contraseñas |
| `tests/auth/test_login.py` | `POST /auth/login`: `login`, `user_service.authenticate` |
| `tests/auth/test_token.py` | `POST /auth/token`: `login_form`, creación y decodificación del JWT de acceso |
| `tests/auth/test_me.py` | `GET /auth/me`: `read_me` y la dependencia `get_current_user` |
| `tests/auth/test_forgot_password.py` | `POST /auth/forgot-password`: `forgot_password`, `_send_reset_link`, `create_password_reset` |
| `tests/auth/test_reset_password.py` | `POST /auth/reset-password`: `reset_password` (ruta y servicio), token de un solo uso |
| `tests/auth/test_change_password.py` | `POST /auth/change-password`: `change_password` (ruta y servicio) |
| `uis/talent-pipeline-tracker/__tests__/auth.test.ts` | `app/lib/auth.ts`: token en `localStorage`, `isTokenExpired`, `getNextPath`, `useToken` y las llamadas `login`, `register`, `getMe`, `updateMyProfile`, `forgotPassword`, `resetPassword`, `changePassword` |

| `uis/talent-pipeline-tracker/__tests__/api.test.ts` | `app/lib/api.ts`: `RecordsApiError`, `isNotFoundError`, `toUserMessage`, `getPhotoUrl`, construcción de URL con filtros, manejo de respuestas y las llamadas de candidaturas, notas y foto |
| `uis/talent-pipeline-tracker/__tests__/constants.test.ts` | `app/lib/constants.ts`: `formatDate`, `getStatusLabel`, `getStageLabel`, opciones de los desplegables y `AUTH_API_URL` |
| `tests/incidents/test_create_incident.py` | `POST /api/incidents`: `create_incident`, `validate_incident_fields` |
| `tests/incidents/test_list_incidents.py` | `GET /api/incidents`: `list_incidents`, `validate_filters`, orden |
| `tests/incidents/test_incidents_summary.py` | `GET /api/incidents/summary`: `incidents_summary` |
| `tests/incidents/test_incident_detail.py` | `GET /api/incidents/{id}`: `get_incident` |
| `tests/incidents/test_incident_status.py` | `PATCH /api/incidents/{id}/status`: `update_incident_status`, `validate_status_transition` (las 16 combinaciones de estados) |
| `tests/incidents/test_incident_search.py` | `GET /api/incidents/search`: `search_incidents`, `incident_service.search`, `incident_text` |
| `tests/incidents/test_incident_similar.py` | `GET /api/incidents/{id}/similar`: `similar_incidents`, marca de posible duplicado |
| `tests/incidents/test_incident_duplicates.py` | `GET /api/incidents/duplicates`: `duplicate_groups` |
| `tests/incidents/test_incident_suggest.py` | `POST /api/incidents/suggest`: `suggest_for_draft`, `suggest_category` |
| `tests/incidents/test_semantic_status.py` | `GET /api/incidents/semantic-status`: `semantic_status`, `ensure_index`, `index_pending` |
| `tests/suppliers/test_create_supplier.py` | `POST /suppliers`: `create_supplier`, `SupplierCreate` |
| `tests/suppliers/test_list_suppliers.py` | `GET /suppliers`: `list_suppliers` y sus filtros |
| `tests/suppliers/test_supplier_detail.py` | `GET /suppliers/{id}`: `get_supplier` |
| `tests/suppliers/test_supplier_rate.py` | `PATCH /suppliers/{id}/rate`: `update_rate`, `RateUpdate`, trazabilidad de `updated_at` |
| `tests/suppliers/test_supplier_status.py` | `PATCH /suppliers/{id}/status`: `update_status`, `StatusUpdate` |
| `tests/suppliers/test_delete_supplier.py` | `DELETE /suppliers/{id}`: `delete_supplier` |

**Probamos la lógica, no la serialización HTTP.** Las pruebas de `tests/auth/` llaman
directamente a las funciones de ruta (`login(LoginRequest(...))`) y a los servicios, sin
`TestClient`: comprueban qué se devuelve, qué excepción se lanza y qué queda guardado. En
Jest, `fetch` está sustituido por un mock: se comprueba qué hace el código con cada
respuesta, no la red.

Las suites que ya existían (`tests/test_auth.py`, `tests/test_auth_passwords.py`,
`tests/test_incidents.py`, `tests/test_api_characterization.py`,
`tests/test_supplier_models_r4a.py`) son pruebas de integración por HTTP o de modelos y se
mantienen tal cual como red de seguridad del contrato.

## Plan de casos — AUTH-088 (autenticación)

Escrito antes que los tests. CF = camino feliz, CL = caso límite, MF = modo de fallo.

### `POST /users` (registro)

- CF: alta con email y contraseña válidos → usuario activo con rol `user` y perfil vinculado.
- CF: la contraseña se guarda como hash bcrypt, nunca en claro, y el hash verifica.
- CL: email ya registrado con otras mayúsculas → 409 y no se crea un segundo usuario.
- CL: contraseña en el límite (8 caracteres, 72 bytes) → aceptada.
- CL: sin datos de perfil → perfil creado con campos a `None`.
- CL: `role: "admin"` enviado por el cliente → se ignora.
- MF: contraseña de 7 caracteres, de 73 bytes, o de 37 caracteres multibyte (74 bytes) → rechazada.
- MF: email mal formado o contraseña ausente → rechazado.
- MF: contraseña con byte NUL → rechazada en validación (ver «Bugs encontrados»).
- MF: falla el alta del perfil → se deshace el alta del usuario.

### `POST /auth/login`

- CF: credenciales correctas → token `bearer` cuyo `sub` es el id del usuario y `expires_in` configurado.
- CL: email con mayúsculas distintas a las registradas → mismo usuario.
- CL: contraseña vacía o de más de 72 bytes → 401, no 500.
- MF: contraseña incorrecta y email inexistente → mismo 401 con el mismo mensaje.
- MF: usuario inactivo con contraseña correcta → 401.
- MF: email inexistente → se gasta igualmente una verificación bcrypt (sin fuga por tiempos).
- MF: email mal formado → rechazado en validación.

### `POST /auth/token` (formulario OAuth2 y JWT)

- CF: `username` = email y contraseña correctos → token que `decode_access_token` resuelve al usuario.
- CF: el token lleva `type=access` y caduca en `ACCESS_TOKEN_EXPIRE_MINUTES`.
- CL: duración personalizada (`expires_minutes=1`) → `exp - iat` de 60 s.
- MF: credenciales incorrectas → 401.
- MF: token caducado, basura, vacío, firmado con otra clave, sin `sub`, con `sub` no textual
  o de tipo `password_reset` → `decode_access_token` devuelve `None`.

### `GET /auth/me`

- CF: `get_current_user` con token válido devuelve el usuario; `read_me` añade su perfil.
- CF: la respuesta (`MeResponse`) no expone `hashed_password`.
- CL: usuario sin perfil → `profile: None`.
- MF: token caducado, basura, de restablecimiento, de usuario inexistente, borrado o inactivo → 401.

### `POST /auth/forgot-password`

- CF: email registrado → se encola el envío; al ejecutarse sale un enlace cuyo token apunta al usuario.
- CF: el token caduca en `PASSWORD_RESET_EXPIRE_MINUTES`.
- CL: email inexistente → misma respuesta, ningún correo ni registro.
- CL: email con otras mayúsculas → encuentra al usuario.
- CL: límite por hora alcanzado → no se emiten más enlaces; los registros de hace más de una hora no cuentan.
- MF: usuario inactivo → no se envía nada.
- MF: el proveedor de correo falla → el enlace se anula, no cuenta en el límite y se registra el id (no el email).
- MF: `cancel_password_reset` con un token ilegible → no hace nada.

### `POST /auth/reset-password`

- CF: token válido → contraseña cambiada; la antigua deja de servir.
- CL: el token es de un solo uso; usar un enlace invalida los demás pendientes.
- CL: nueva contraseña en el límite (8 caracteres) → aceptada.
- MF: token caducado, basura, manipulado, con `jti` no emitido o de sesión → 400 y contraseña intacta.
- MF: usuario inactivo o borrado tras emitir el enlace → 400.
- MF: nueva contraseña corta, de más de 72 bytes o con NUL → rechazada sin consumir el enlace.

### `POST /auth/change-password`

- CF: contraseña actual correcta → cambiada; la antigua deja de servir.
- CL: los enlaces de restablecimiento pendientes quedan invalidados.
- MF: contraseña actual incorrecta o vacía → 400 y contraseña intacta.
- MF: el usuario de la sesión ya no existe → 400.
- MF: nueva contraseña corta, de más de 72 bytes o con NUL → rechazada.

### `app/lib/auth.ts` (Jest)

- Token: guardar, leer y borrar; `localStorage` bloqueado → `setToken` devuelve `false` y `getToken` `null`.
- `isTokenExpired`: CF `exp` futuro; CL `exp` igual a ahora, payload base64url; MF `exp` pasado, ausente, no numérico, token ilegible.
- `getNextPath`: CF ruta interna (con query); CL sin `next` o vacío; MF `//host`, `/\host`, URL absoluta, tabulador/salto de línea colado.
- `useToken`: refleja `setToken`/`clearToken` y los cambios hechos en otra pestaña.
- `login`: CF guarda el token; MF 401, 422 con errores por campo, 500, sin red, respuesta ilegible, sin `access_token`, almacenamiento bloqueado.
- `register`: CF alta + login; MF 409 (email duplicado), 422 con mensajes traducidos.
- `getMe` / `updateMyProfile`: CF con cabecera `Authorization`; MF sin token, token caducado (no se llama a la API), 401 de la API (se cierra la sesión), 500.
- `forgotPassword` / `resetPassword` / `changePassword`: CF; MF 400 y 422 con su mensaje.

## Plan de casos — API-042 (incidencias y proveedores)

Mismo criterio que en autenticación: un módulo por endpoint, llamando a la función de ruta y a
los servicios sin `TestClient`, con CF, CL y MF en cada uno. Se eligieron estos dos grupos
porque incidencias concentra la lógica más compleja del backoffice (ciclo de vida, filtros,
capa semántica) y proveedores era el recurso con menos protección en sus rutas.

Las pruebas semánticas usan el proveedor de embeddings `hashing` (determinista, sin descargar
ningún modelo), que es el que fija `tests/conftest.py`.

### Incidencias (`/api/incidents`)

**`POST /api/incidents`** — `test_create_incident.py`
- CF: alta válida → `status` `open`, `created_at == updated_at`, se encola el indexado.
- CL: título y descripción con espacios → se guardan recortados; título de 120 y descripción de 5000 caracteres → aceptados.
- CL: `id` y `created_at` enviados por el cliente → se ignoran; `status` vacío → `open`.
- MF: falta un campo obligatorio, o solo tiene espacios → error `required` con el campo.
- MF: título de 121 caracteres, descripción de 5001 → `too_long`; título no textual → `invalid_type`.
- MF: categoría, origen, sede o estado no permitidos (incluidos listas y objetos) → `invalid_value`.
- MF: varios campos mal → se informan todos y no se guarda nada.

**`GET /api/incidents`** — `test_list_incidents.py`
- CF: devuelve las incidencias, las más recientes primero.
- CL: sin incidencias → lista vacía; filtros vacíos (`""`) → se ignoran; misma fecha → desempata el id.
- CL: varios filtros → se combinan con AND; filtro sin coincidencias → lista vacía.
- MF: filtro con valor no permitido → error con el campo; varios filtros mal → todos.

**`GET /api/incidents/summary`** — `test_incidents_summary.py`
- CF: totales por estado, categoría, origen y sede.
- CL: sin incidencias → todos los valores posibles a 0; cada bloque suma el total.
- MF: un cambio de estado mueve la incidencia de contador (no se cuenta dos veces); un alta rechazada no cuenta.

**`GET /api/incidents/{id}`** — `test_incident_detail.py`
- CF: devuelve la incidencia creada.
- CL: ids 0 y negativos → 404.
- MF: id inexistente → 404 con el id en el mensaje.

**`PATCH /api/incidents/{id}/status`** — `test_incident_status.py`
- CF: `open → in_progress → resolved`, `open → discarded`, `in_progress → discarded`; cambia `updated_at`, no `created_at`.
- CL: mismo estado (`open → open`) → rechazado; campos extra del cuerpo → ignorados.
- MF: saltos no permitidos y estados finales → `invalid_transition`, y el estado no cambia.
- MF: `status` ausente, vacío, desconocido o no textual → error; incidencia inexistente → 404.

**`GET /api/incidents/search`** — `test_incident_search.py`
- CF: la incidencia más parecida sale la primera, con `score`.
- CL: `limit` recorta; filtros combinables; base vacía → `[]`; consulta sin palabras (`"!!!"`) → `[]`.
- CL: `incident_text` no repite el título si la descripción ya empieza por él.
- MF: consulta vacía o de espacios → `required`; filtro no permitido → error.
- MF: el proveedor de embeddings falla → 503; un error de programación no se disfraza de 503.

**`GET /api/incidents/{id}/similar`** — `test_incident_similar.py`
- CF: devuelve casos parecidos, sin incluir la propia incidencia.
- CL: sin parecidas → `[]`; `possible_duplicate` solo si la parecida está activa.
- MF: incidencia inexistente → 404; proveedor caído → 503.

**`GET /api/incidents/duplicates`** — `test_incident_duplicates.py`
- CF: agrupa incidencias activas casi idénticas, con sedes y orígenes del grupo.
- CL: menos de dos activas → `[]`; resueltas y descartadas no cuentan; grupos mayores primero.
- MF: proveedor caído → 503.

**`POST /api/incidents/suggest`** — `test_incident_suggest.py`
- CF: borrador parecido al histórico → similares y categoría sugerida con confianza.
- CL: solo título o solo descripción → vale; sin histórico → sin sugerencia.
- CL (`suggest_category`): sin categoría dominante → sin sugerencia; vecinas por debajo del umbral no votan; solo votan las 5 primeras.
- MF: borrador vacío o con campos no textuales → `required`; proveedor caído → 503.

**`GET /api/incidents/semantic-status`** — `test_semantic_status.py`
- CF: proveedor activo, indexadas y pendientes.
- CL: base vacía → todo a 0; embeddings de otro modelo → se recalculan.
- MF: si el proveedor falla al indexar tras un alta, la incidencia queda pendiente y no se pierde.

### Proveedores (`/suppliers`)

**`POST /suppliers`** — `test_create_supplier.py`
- CF: alta válida → `id` y `updated_at` puestos por el servidor.
- CL: `id`/`updated_at` del cliente → ignorados; opcionales ausentes → `None`; varias categorías.
- MF: país y moneda incoherentes; tarifa 0 o negativa; categorías vacías o desconocidas; nombre vacío.
- MF: tarifa infinita o NaN, y nombre de solo espacios → rechazados (ver «Bugs encontrados»).

**`GET /suppliers`** — `test_list_suppliers.py`
- CF: lista todos; filtra por país y por categoría.
- CL: sin proveedores → `[]`; país + categoría → AND; proveedor con varias categorías aparece en cada una.
- MF: filtro sin coincidencias → `[]` (no error).

**`GET /suppliers/{id}`** — `test_supplier_detail.py`
- CF: devuelve el proveedor; CL: ids 0 y negativos → 404; MF: inexistente o ya borrado → 404.

**`PATCH /suppliers/{id}/rate`** — `test_supplier_rate.py`
- CF: cambia la tarifa y `updated_at` (trazabilidad de tarifas).
- CL: misma tarifa → `updated_at` también se renueva; el resto de campos no cambia.
- MF: tarifa 0, negativa, infinita o NaN → rechazada; proveedor inexistente → 404.

**`PATCH /suppliers/{id}/status`** — `test_supplier_status.py`
- CF: suspender y reactivar.
- CL: un cambio de estado **no** toca `updated_at`; repetir el mismo estado es inocuo.
- MF: estado desconocido → rechazado; proveedor inexistente → 404.

**`DELETE /suppliers/{id}`** — `test_delete_supplier.py`
- CF: devuelve el proveedor tal como estaba y deja de existir.
- CL: borrar uno no afecta a los demás; devuelve el último estado guardado.
- MF: borrar dos veces o un id inexistente → 404.

## Plan de casos — FE-019 (utilidades del frontend)

El ticket pide al menos tres funciones con un camino feliz y un modo de fallo cada una. Se
cubren todas las utilidades exportadas de `app/lib/` que no eran de autenticación (esas ya
estaban en `auth.test.ts`).

### Formateadores — `constants.test.ts`

- `formatDate`: CF fecha ISO → día, mes y año en español con hora local; CL fecha sin hora;
  MF fecha ilegible, vacía, imposible o ausente → `—` (ver «Bugs encontrados»).
- `getStatusLabel` / `getStageLabel`: CF cada valor → su etiqueta en español; MF valor que la
  UI no conoce → se muestra el valor tal cual, sin romper; CL distinta capitalización o un
  estado usado como etapa no se resuelven por error.
- Opciones de los desplegables: una por valor permitido, en el mismo orden, y ninguna muestra
  el valor en bruto como etiqueta.
- `AUTH_API_URL`: CF usa la dirección configurada; CL quita la barra final; MF sin configurar
  → API local.

### Manejo de respuestas de la API — `api.test.ts`

- `RecordsApiError`: CF mensaje para el usuario según el tipo; CL sin respuesta → estado 0;
  el código de estado nunca aparece en el texto.
- `isNotFoundError`: CF error `not_found`; MF otro tipo de error, un `Error` que menciona 404,
  un objeto parecido, `null`, `undefined`.
- `toUserMessage`: CF mensaje del error de la API; MF error del navegador, texto lanzado,
  `null` → mensaje genérico, nunca el detalle técnico.
- `getPhotoUrl`: CF ruta local de la foto; CL con versión (para recargar la foto); MF versión
  0 o ausente → sin parámetro; nunca devuelve una URL absoluta.
- `listRecords`: CF devuelve la página; CL envía solo los filtros con valor y codifica
  espacios, acentos y `&`/`#`; fija un tiempo de espera.
- Manejo común: 404 → `not_found`; 400 y 422 → `validation`; 401, 409, 500, 503 → `server`;
  fallo de red o tiempo agotado → `network`; respuesta correcta pero ilegible → `server`.
- `getRecord`, `createRecord`, `patchRecord`, `putRecord`, `deleteRecord`, `listNotes`,
  `createNote`, `deleteNote`, `uploadPhoto`: CF con método, URL y cuerpo correctos; CL
  respuesta envuelta en `{ data }`, lista vacía, borrado sin cuerpo; MF el error que
  corresponde a cada una.

## Por qué estos casos

- **Un módulo por endpoint y tres tipos de caso en cada uno** (CF, CL, MF), como pide el ticket.
- **Los límites salen del código, no de una lista genérica**: 8 caracteres y 72 bytes son los
  límites reales de `_check_password`; el máximo de enlaces por hora y la ventana de caducidad
  son los de `config.py`.
- **Los modos de fallo priorizan seguridad**: mismo error para email inexistente y contraseña
  incorrecta, tokens de un tipo que no sirven para otro, enlaces de un solo uso, usuario
  desactivado o borrado con un token todavía vigente.
- **Cada test comprueba el efecto, no solo el código de estado**: tras un fallo se verifica que
  la contraseña sigue siendo la de antes; tras un éxito, que la antigua ya no sirve.
- **El reloj se controla** (`user_service._now`, `Date.now`) en vez de esperar: caducidades y
  límites por hora se prueban sin `sleep`.

## Bugs encontrados por los tests

Todos salieron de pedir casos límite a la IA sobre la lógica de cada endpoint; el test falló
primero y después se corrigió el código.

### AUTH-088

1. **Contraseña con byte NUL → error 500** (`services/api/user_models.py`).
   `_check_password` aceptaba `"abcdefg\x00hij"`, pero bcrypt no admite NUL y `hash_password`
   lanzaba `ValueError`: registro, restablecimiento y cambio de contraseña respondían 500 en
   lugar de 422. Ahora la validación la rechaza.
   Tests: `test_register_rejects_password_with_nul_byte` y los parametrizados
   `..._rejects_invalid_new_password` de reset y change.
2. **Redirección abierta tras el login** (`uis/talent-pipeline-tracker/app/lib/auth.ts`).
   `getNextPath` aceptaba `?next=/%09/evil.com`: el navegador elimina tabuladores y saltos de
   línea de las URL, así que `/<tab>/evil.com` se convierte en `//evil.com` y lleva a otro
   dominio. Ahora se rechaza cualquier `next` con `\t`, `\n` o `\r`.
   Tests: `getNextPath › rejects a tab/newline/carriage return ...`.

### API-042

3. **Tarifa infinita aceptada y devuelta como `null`** (`services/api/models.py`).
   Un JSON con `"rate_per_shipment": 1e999` (o `Infinity`) llega a Python como infinito y
   cumple `gt=0`: el proveedor se guardaba con tarifa infinita y la API la devolvía como
   `null`, tanto al crear como al cambiar la tarifa. `SupplierCreate` y `SupplierRateUpdate`
   exigen ahora un número finito.
   Tests: `test_create_rejects_non_finite_rate`, `test_update_rate_rejects_invalid_rate[inf]`.
4. **Proveedor con nombre en blanco** (`services/api/models.py`).
   `min_length=1` aceptaba `"   "`, así que se podía dar de alta un proveedor sin nombre
   visible. `SupplierCreate` rechaza ahora los nombres formados solo por espacios.
   Tests: `test_create_rejects_name_made_only_of_whitespace`.

### FE-019

5. **«Invalid Date» en pantalla** (`uis/talent-pipeline-tracker/app/lib/constants.ts`).
   `formatDate` devolvía el texto `Invalid Date` (en inglés, dentro de una interfaz en
   español) si la fecha llegaba vacía o ilegible; se usa en la ficha de la candidatura y en
   cada nota. Ahora devuelve `—`.
   Tests: `formatDate › shows a dash instead of 'Invalid Date' ...`.

Nota sobre API-042: las dos validaciones están solo en los modelos de entrada: `SupplierResponse` no cambia, así
que un registro antiguo que ya tuviera esos valores se sigue pudiendo leer.

En incidencias no apareció ningún bug: los 185 tests pasaron contra el código tal como estaba.

## Resultados

| Comando | Resultado |
| --- | --- |
| `uv run pytest` | 640 pasan: 107 en `tests/auth/`, 185 en `tests/incidents/`, 75 en `tests/suppliers/` y las 273 que ya existían |
| `uv run pytest --cov` | `services/api` 91 % en total |
| `npx jest --coverage` | 148 pasan: 64 en `auth.test.ts`, 59 en `api.test.ts`, 25 en `constants.test.ts` |

### FE-019 — utilidades del frontend

Cobertura de `npx jest --coverage` sobre `app/lib/`:

| Módulo | Líneas | Ramas |
| --- | --- | --- |
| `app/lib/api.ts` | 100 % | 100 % |
| `app/lib/auth.ts` | 100 % | 100 % |
| `app/lib/constants.ts` | 100 % | 87,5 % |

Las dos ramas sin cubrir de `constants.ts` son el `?? value` de las etiquetas de los
desplegables, que solo se ejecutaría si se añadiera un valor nuevo sin su traducción.

### AUTH-088 — objetivo 70 % en el módulo de autenticación

Cobertura obtenida solo con `uv run pytest tests/auth --cov`:

| Módulo | Cobertura |
| --- | --- |
| `services/api/routes/auth.py` | 100 % |
| `services/api/user_models.py` | 99 % |
| `services/api/security.py` | 91 % |
| `services/api/user_service.py` | 89 % |

### API-042 — objetivo 60 % en los módulos probados

Cobertura obtenida solo con `uv run pytest tests/incidents tests/suppliers --cov`:

| Módulo | Antes (solo `tests/auth`) | Ahora |
| --- | --- | --- |
| `services/api/routes/incidents.py` | 42 % | 100 % |
| `services/api/incident_service.py` | 20 % | 100 % |
| `services/api/routes/suppliers.py` | 44 % | 100 % |
| `services/api/models.py` | 89 % | 100 % |
| `services/api/store.py` | 60 % | 92 % |
| `services/api/embeddings.py` | 47 % | 81 % |
| `packages/shared/incident_model.py` (con `--cov=packages/shared`) | — | 75 % |

Lo que queda sin cubrir en estos módulos es ajeno a los endpoints: la carga del modelo
`fastembed` real en `embeddings.py`, la apertura de un archivo TinyDB corrupto en `store.py` y
la transformación CSV → incidencia del seed en `incident_model.py` (ya probada en
`tests/test_incidents.py`).

## Fuera de alcance y observaciones

- `services/api/email_service.py` (plantilla y envío con Resend) no forma parte de la lógica de
  los endpoints; lo cubren las pruebas de integración de `tests/test_auth_passwords.py`.
- `uis/backoffice/auth.js` es JavaScript sin módulo exportable y no entra en la batería de Jest.
- Comportamientos observados que **no** se han fijado con tests porque son decisión de producto,
  no bugs: cambiar la contraseña por la misma está permitido, y los tokens de sesión ya emitidos
  siguen valiendo hasta caducar después de cambiar o restablecer la contraseña.
- Observaciones de API-042, tampoco fijadas con tests por el mismo motivo:
  - Se pueden dar de alta dos proveedores con el mismo nombre, y `contact_email` no se valida
    como email.
  - Una incidencia se puede crear directamente en un estado final (`resolved`, `discarded`);
    lo necesita el seed, pero la API pública también lo permite.
  - En la sugerencia de categoría, un empate exacto entre dos categorías (50 % cada una)
    devuelve la primera con confianza 0,5, aunque la intención documentada es sugerir solo
    cuando hay una claramente dominante.
- Fuera de FE-019:
  - Los validadores de los formularios de registro y de cambio de contraseña (`validate`) son
    funciones privadas de sus páginas; Next.js no permite exportarlas desde un `page.tsx`, así
    que para probarlas habría que moverlas antes a `app/lib/`.
  - `src/utils/*.ts`, en la raíz del repositorio, no pertenece al proyecto Next.js (no tiene
    `package.json` ni `tsconfig.json`) y Jest no lo alcanza.
  - Observación: si la API de candidaturas respondiera con un JSON válido pero con otra forma
    (por ejemplo sin `data` en el listado de notas), `api.ts` lo devolvería tal cual y fallaría
    la pantalla que lo usa. No se ha cambiado porque hoy la API cumple el contrato.
- Usuarios, perfiles y el analizador CSV no entran en API-042; siguen cubiertos solo por las
  pruebas HTTP existentes.
