# Auditoría de serialización — API FastAPI de TrackFlow

> Fase 1 (auditoría) → Fase 2 (implementación) → Fase 3 (verificación). Completado: los 40
> endpoints quedan en ✅. Los casos dudosos de la Fase 1 se resolvieron con las 6 propuestas
> confirmadas (ver el final del documento).

## Contexto técnico

| Pieza | Valor |
|---|---|
| App FastAPI | `services/api/main.py` (FastAPI 0.142.2) |
| Pydantic | **v2** (2.13.5) → los esquemas usan `model_config = ConfigDict(from_attributes=True)` cuando leen objetos ORM |
| Persistencia | TinyDB (usuarios, perfiles, proveedores, incidencias: devuelve `dict`) y SQLModel/Supabase (inventario: devuelve objetos ORM) |
| Routers | `services/api/routes/{auth,users,profiles,suppliers,incidents}.py`, `services/routers/inventory.py`, y 3 rutas sueltas en `main.py` |
| Esquemas existentes | `services/api/user_models.py`, `services/api/models.py` (proveedores), `services/schemas.py` (inventario) |
| Consumidor | Backoffice Next.js: `uis/backoffice/app/lib/{auth,suppliers,incidents,inventory}.ts` y las pantallas de `app/(protected)/`. La web pública (`uis/website`) no llama a la API |
| Tests | `uv run pytest` (raíz del repo) |
| Línea base (antes de cambiar nada) | App arranca (`GET /` → 200, `/openapi.json` generado). **773 passed**, 0 fallos |

### Conceptos que se usan en este documento

- **`response_model`**: le dice a FastAPI qué forma tiene la respuesta. FastAPI *filtra* lo que
  devuelve el handler y se queda solo con los campos del esquema. Es la última barrera para que
  no se escape un campo (p. ej. `hashed_password`) aunque el handler devuelva el dict completo
  de la base de datos. Además documenta la respuesta en `/docs` y `/openapi.json`.
- **Esquema de entrada separado del de salida**: el de entrada solo lista lo que el cliente puede
  escribir. Así se evita la *asignación masiva* (que un cliente envíe `id`, `role` o
  `created_at` y el servidor lo guarde).
- **Esquema de listado más ligero**: un listado devuelve N elementos; cada campo innecesario se
  multiplica por N (más bytes, más datos expuestos).

## Tabla resumen

| Ruta | Método | Estado original | Estado final |
|---|---|---|---|
| `/auth/login` | POST | ✅ | ✅ |
| `/auth/token` | POST | ✅ | ✅ |
| `/auth/me` | GET | ⚠️ | ✅ |
| `/auth/forgot-password` | POST | ✅ | ✅ |
| `/auth/reset-password` | POST | ✅ | ✅ |
| `/auth/change-password` | POST | ✅ | ✅ |
| `/users` | POST | ⚠️ | ✅ |
| `/users` | GET | ⚠️ | ✅ |
| `/users/{user_id}` | GET | ✅ | ✅ |
| `/users/{user_id}` | PUT | ✅ | ✅ |
| `/users/{user_id}` | DELETE | ✅ | ✅ |
| `/profiles/me` | GET | ✅ | ✅ |
| `/profiles/me` | PUT | ✅ | ✅ |
| `/profiles/{user_id}` | GET | ✅ | ✅ |
| `/profiles/{user_id}` | PUT | ✅ | ✅ |
| `/suppliers` | POST | ✅ | ✅ |
| `/suppliers` | GET | ✅ | ✅ |
| `/suppliers/{supplier_id}` | GET | ✅ | ✅ |
| `/suppliers/{supplier_id}/rate` | PATCH | ✅ | ✅ |
| `/suppliers/{supplier_id}/status` | PATCH | ✅ | ✅ |
| `/suppliers/{supplier_id}` | DELETE | ✅ | ✅ |
| `/api/incidents` | POST | ❌ | ✅ |
| `/api/incidents` | GET | ❌ | ✅ |
| `/api/incidents/summary` | GET | ❌ | ✅ |
| `/api/incidents/search` | GET | ❌ | ✅ |
| `/api/incidents/semantic-status` | GET | ❌ | ✅ |
| `/api/incidents/duplicates` | GET | ❌ | ✅ |
| `/api/incidents/suggest` | POST | ❌ | ✅ |
| `/api/incidents/{incident_id}` | GET | ❌ | ✅ |
| `/api/incidents/{incident_id}/similar` | GET | ❌ | ✅ |
| `/api/incidents/{incident_id}/status` | PATCH | ❌ | ✅ |
| `/inventory/products` | GET | ✅ | ✅ |
| `/inventory/products` | POST | ✅ | ✅ |
| `/inventory/products/{sku_id}` | GET | ✅ | ✅ |
| `/inventory/orders/inbound` | POST | ✅ | ✅ |
| `/inventory/orders/outbound` | POST | ✅ | ✅ |
| `/inventory/orders` | GET | ⚠️ | ✅ |
| `/` | GET | ❌ | ✅ |
| `/analyze` | POST | ❌ | ✅ |
| `/api/incidents/results/export` | GET | ⚠️ | ✅ |

**Totales originales (40 endpoints): ✅ 23 · ⚠️ 5 · ❌ 12. Estado final: ✅ 40.**

---

# Autenticación

## POST /auth/login
- Propósito: iniciar sesión con JSON y obtener un JWT.
- Consumidor y campos que usa: `uis/backoffice/app/lib/auth.ts` → `login()` lee solo `access_token`. Envía `{email, password}`.
- Estado original: ✅ `response_model=Token`; el handler devuelve un dict construido a mano con los tres campos del token. No sale ni email ni contraseña.
- Esquema de entrada: `LoginRequest` → `email`, `password`.
- Esquema de salida objetivo: `Token` → `access_token`, `token_type`, `expires_in`. (`token_type` y `expires_in` son parte del estándar OAuth2; se mantienen aunque el front no los lea.)
- Decisión sobre relaciones: no aplica.
- Cambios aplicados: ninguno; ya cumplía. Se revisó que el `response_model` existente coincide con el consumidor.
- Estado final: ✅

## POST /auth/token
- Propósito: mismo login en formato formulario OAuth2; lo usa el botón «Authorize» de `/docs`.
- Consumidor y campos que usa: no lo llama el backoffice; solo Swagger UI (`access_token`, `token_type`).
- Estado original: ✅ `response_model=Token`.
- Esquema de entrada: `OAuth2PasswordRequestForm` (form-data `username`, `password`), estándar de FastAPI.
- Esquema de salida objetivo: `Token` (igual que `/auth/login`; compartirlo es correcto porque el contrato es idéntico).
- Decisión sobre relaciones: no aplica.
- Cambios aplicados: ninguno; ya cumplía. Se revisó que el `response_model` existente coincide con el consumidor.
- Estado final: ✅

## GET /auth/me
- Propósito: datos del usuario autenticado; el guard del backoffice lo usa para validar la sesión.
- Consumidor y campos que usa: `app/ui/auth-guard.tsx` (`getMe()`), `app/ui/backoffice-header.tsx` y `trackflow-header.tsx` (`email`, `profile.name`), `app/(protected)/account/profile/page.tsx` (`email`, `role`, `profile.name/phone/address`), `app/(protected)/inventory/orders/orders-client.tsx` (`id`, para marcar «Tú»).
- Estado original: ⚠️ `response_model=MeResponse` correcto en lo principal, pero el `profile` anidado reutiliza `ProfileResponse`, que incluye `profile.id` (id interno del perfil) y `profile.user_id` (clave foránea en bruto que **repite** el `id` de nivel superior). Ningún consumidor los lee.
- Esquema de entrada: ninguno (solo el token).
- Esquema de salida objetivo: `MeResponse` → `id`, `email`, `role`, `profile: ProfileSummary | null` con `ProfileSummary` → `name`, `phone`, `address`. Aquí sí se devuelve `email`: es el propio usuario.
- Decisión sobre relaciones: **proyección anidada reducida**. El perfil es 1:1 con el usuario y el front lo lee como `me.profile.name`, así que se mantiene anidado (aplanarlo rompería el front), pero sin sus claves (`id`, `user_id`), que no aportan nada aquí.
- Cambios aplicados: nuevo `ProfileSummary` (`name`, `phone`, `address`) en `services/api/user_models.py`; `MeResponse.profile` pasa de `ProfileResponse` a `ProfileSummary`. Verificado por HTTP: la respuesta ya no lleva `profile.id` ni `profile.user_id`.
- Estado final: ✅
- Impacto en frontend: ninguno en ejecución. El tipo TS `Me.profile` (`app/lib/types.ts`) declara `id` y `user_id`; conviene cambiarlo a `Pick<Profile, "name" | "phone" | "address">` para que el tipo diga la verdad.

## POST /auth/forgot-password
- Propósito: pedir un enlace de restablecimiento.
- Consumidor y campos que usa: `lib/auth.ts` → `forgotPassword()` solo mira `response.ok`. Envía `{email}`.
- Estado original: ✅ `MessageResponse`; mensaje genérico idéntico exista o no el email (no revela qué emails están registrados).
- Esquema de entrada: `ForgotPasswordRequest` → `email`.
- Esquema de salida objetivo: `MessageResponse` → `message`.
- Decisión sobre relaciones: no aplica.
- Cambios aplicados: ninguno; ya cumplía. Se revisó que el `response_model` existente coincide con el consumidor.
- Estado final: ✅

## POST /auth/reset-password
- Propósito: fijar una contraseña nueva con el token del correo.
- Consumidor y campos que usa: `lib/auth.ts` → `resetPassword()` solo mira el código de estado. Envía `{token, new_password}`.
- Estado original: ✅ `MessageResponse`.
- Esquema de entrada: `ResetPasswordRequest` → `token`, `new_password`.
- Esquema de salida objetivo: `MessageResponse` → `message`.
- Decisión sobre relaciones: no aplica.
- Cambios aplicados: ninguno; ya cumplía. Se revisó que el `response_model` existente coincide con el consumidor.
- Estado final: ✅

## POST /auth/change-password
- Propósito: cambiar la contraseña estando autenticado.
- Consumidor y campos que usa: `lib/auth.ts` → `changePassword()` solo mira el código. Envía `{current_password, new_password}`.
- Estado original: ✅ `MessageResponse`.
- Esquema de entrada: `ChangePasswordRequest` → `current_password`, `new_password`.
- Esquema de salida objetivo: `MessageResponse` → `message`.
- Decisión sobre relaciones: no aplica.
- Cambios aplicados: ninguno; ya cumplía. Se revisó que el `response_model` existente coincide con el consumidor.
- Estado final: ✅

---

# Usuarios

## POST /users
- Propósito: registro público (rol siempre `user`) con perfil inicial opcional.
- Consumidor y campos que usa: `lib/auth.ts` → `register()`; **no lee el cuerpo**, solo el código (201/409/422) y después hace login. Envía `{email, password, name?, phone?, address?}`.
- Estado original: ⚠️ `response_model=UserWithProfileResponse` devuelve `id`, `email`, `is_active`, `role`, `created_at` y el perfil con `id` y `user_id`. Incumple la regla de que el registro **no devuelve el email**, y expone FKs y timestamps que nadie usa. (No sale el hash: ya estaba filtrado.)
- Esquema de entrada: `UserCreate` → `email`, `password`, `name`, `phone`, `address`. No acepta `role` (si llega se ignora; hay test que lo verifica).
- Esquema de salida objetivo: `RegisterResponse` → `id`, `role`, `is_active`, `profile: ProfileSummary | null` (`name`, `phone`, `address`). Sin `email`, sin `created_at`, sin `profile.id`/`profile.user_id`.
- Decisión sobre relaciones: proyección anidada reducida del perfil (mismo `ProfileSummary` que `/auth/me`), para que se pueda comprobar que el perfil se creó sin exponer claves.
- Cambios aplicados: nuevo `RegisterResponse` en `user_models.py` y `response_model=RegisterResponse` en `routes/users.py`. Se elimina `UserWithProfileResponse` (sin otros usos). Tests: `tests/test_auth.py` y `tests/auth/test_register.py` pasan a afirmar que el email **no** sale; los fixtures `alice`/`bob` (`test_auth.py`) y `user` (`test_auth_passwords.py`) guardan el email que ellos mismos generan, porque ya no viene en la respuesta.
- Estado final: ✅
- ⚠️ Conflicto con tests: `tests/test_auth.py::test_register_creates_user_with_default_role_and_linked_profile` afirma `body["email"] == email` y `body["profile"]["user_id"] == body["id"]` por HTTP. Es el **test** el que fija un comportamiento que la regla de seguridad prohíbe. Ver «Casos dudosos».

## GET /users
- Propósito: listado de todos los usuarios (solo admin).
- Consumidor y campos que usa: **sin consumidor** en el monorepo (solo tests y `/docs`).
- Estado original: ⚠️ `response_model=list[UserResponse]`: reutiliza el esquema de detalle, incluido `created_at` (timestamp de auditoría).
- Esquema de entrada: ninguno.
- Esquema de salida objetivo: `list[UserListItem]` → `id`, `email`, `role`, `is_active` (lo mínimo para que un admin identifique y gestione cuentas).
- Decisión sobre relaciones: solo campos planos; el perfil no se incluye (evita N lecturas extra y datos personales en masa).
- Cambios aplicados: nuevo `UserListItem` (`id`, `email`, `role`, `is_active`) y `response_model=list[UserListItem]`.
- Estado final: ✅

## GET /users/{user_id}
- Propósito: detalle de un usuario (él mismo o admin).
- Consumidor y campos que usa: sin consumidor en el monorepo.
- Estado original: ✅ `UserResponse` → `id`, `email`, `is_active`, `role`, `created_at`. Nunca `hashed_password`.
- Esquema de entrada: ninguno.
- Esquema de salida objetivo: `UserResponse` (sin cambios; es el detalle, `created_at` tiene sentido aquí).
- Decisión sobre relaciones: sin perfil (está en `/profiles/{user_id}`).
- Cambios aplicados: ninguno; ya cumplía. Se revisó que el `response_model` existente coincide con el consumidor.
- Estado final: ✅

## PUT /users/{user_id}
- Propósito: actualizar credenciales (email, contraseña) y, solo admin, `role`/`is_active`.
- Consumidor y campos que usa: sin consumidor en el monorepo.
- Estado original: ✅ entrada `UserUpdate` con todos los campos opcionales y `exclude_unset=True` (actualización parcial); salida `UserResponse`.
- Esquema de entrada: `UserUpdate` → `email`, `password`, `role`, `is_active`. Nota: `role`/`is_active` son campos privilegiados, pero el handler ya los restringe a admin con 403; quitarlos cambiaría la lógica de negocio, así que se mantienen y se documenta.
- Esquema de salida objetivo: `UserResponse`.
- Decisión sobre relaciones: no aplica.
- Cambios aplicados: ninguno; ya cumplía. Se revisó que el `response_model` existente coincide con el consumidor.
- Estado final: ✅

## DELETE /users/{user_id}
- Propósito: borrar usuario y perfil; devuelve el usuario tal como era.
- Consumidor y campos que usa: sin consumidor en el monorepo.
- Estado original: ✅ `UserResponse`.
- Esquema de entrada: ninguno.
- Esquema de salida objetivo: `UserResponse`.
- Decisión sobre relaciones: no aplica.
- Cambios aplicados: ninguno; ya cumplía. Se revisó que el `response_model` existente coincide con el consumidor.
- Estado final: ✅

---

# Perfiles

## GET /profiles/me · PUT /profiles/me · GET /profiles/{user_id} · PUT /profiles/{user_id}
(Cuatro endpoints con el mismo contrato; se documentan juntos.)
- Propósito: leer/actualizar el perfil propio o (admin) el de otro usuario.
- Consumidor y campos que usa: `lib/auth.ts` → `updateMyProfile()` (`PUT /profiles/me`) envía `{name, phone, address}`; la pantalla `account/profile/page.tsx` no lee campos concretos de la respuesta. Las rutas `/{user_id}` no tienen consumidor.
- Estado original: ✅ `ProfileResponse` → `id`, `user_id`, `name`, `phone`, `address`. Aquí `user_id` es el identificador del recurso que se pide, no una FK redundante dentro de otro objeto.
- Esquema de entrada (PUT): `ProfileUpdate` → `name`, `phone`, `address`, opcionales, con `exclude_unset=True`.
- Esquema de salida objetivo: `ProfileResponse` (sin cambios).
- Decisión sobre relaciones: solo ID (`user_id`) del usuario dueño.
- Cambios aplicados: ninguno; ya cumplía. Se revisó que el `response_model` existente coincide con el consumidor.
- Estado final: ✅

---

# Proveedores (todas las rutas requieren JWT)

## POST /suppliers
- Propósito: alta de proveedor.
- Consumidor y campos que usa: `app/(protected)/suppliers/suppliers-client.tsx` → lee `created.name` y `created.id`; envía `SupplierDraft` (todos los campos salvo `id` y `updated_at`).
- Estado original: ✅ entrada `SupplierCreate`, salida `SupplierResponse`.
- Esquema de entrada: `SupplierCreate` → `name`, `country`, `categories`, `rate_per_shipment`, `currency`, `status`, `service_zone`, `contact_email`, `notes`. Si llega `id`/`updated_at` se **ignoran** (decisión ya tomada y cubierta por `test_create_ignores_id_and_updated_at_sent_by_client`); por eso **no** se usa `extra="forbid"`.
- Esquema de salida objetivo: `SupplierResponse` (todos los campos + `id`, `updated_at`).
- Decisión sobre relaciones: no aplica.
- Cambios aplicados: ninguno; ya cumplía. Se revisó que el `response_model` existente coincide con el consumidor. No se añade `extra="forbid"` (decisión previa de ignorar `id`/`updated_at`, con test).
- Estado final: ✅

## GET /suppliers
- Propósito: listado con filtros `country` y `category`.
- Consumidor y campos que usa: `suppliers-client.tsx` lee **todos** los campos: `id`, `name`, `country`, `categories`, `rate_per_shipment`, `currency`, `status`, `service_zone`, `contact_email`, `notes`, `updated_at`.
- Estado original: ✅ `list[SupplierResponse]`.
- Esquema de salida objetivo: `list[SupplierResponse]`. Excepción justificada a «listado más ligero»: la lista de campos del consumidor coincide exactamente con el detalle (la tarjeta del proveedor muestra todo, y tras editar se sustituye el elemento por la respuesta del PATCH).
- Decisión sobre relaciones: no aplica.
- Cambios aplicados: ninguno; ya cumplía. Se revisó que el `response_model` existente coincide con el consumidor.
- Estado final: ✅

## GET /suppliers/{supplier_id} · DELETE /suppliers/{supplier_id}
- Propósito: detalle / borrado (devuelve el proveedor borrado).
- Consumidor y campos que usa: sin consumidor en el backoffice.
- Estado original: ✅ `SupplierResponse`.
- Esquema de salida objetivo: `SupplierResponse`.
- Decisión sobre relaciones: no aplica.
- Cambios aplicados: ninguno; ya cumplía. Se revisó que el `response_model` existente coincide con el consumidor.
- Estado final: ✅

## PATCH /suppliers/{supplier_id}/rate · PATCH /suppliers/{supplier_id}/status
- Propósito: cambiar tarifa / estado.
- Consumidor y campos que usa: `suppliers-client.tsx` envía `{rate_per_shipment}` / `{status}` y sustituye la tarjeta con la respuesta completa (`onUpdated(...)`), así que necesita todos los campos.
- Estado original: ✅ entrada `SupplierRateUpdate` / `SupplierStatusUpdate` (un solo campo cada una), salida `SupplierResponse`.
- Esquema de salida objetivo: `SupplierResponse`.
- Decisión sobre relaciones: no aplica.
- Cambios aplicados: ninguno; ya cumplía. Se revisó que el `response_model` existente coincide con el consumidor.
- Estado final: ✅

---

# Incidencias (todas las rutas requieren JWT)

Problema común: **ninguna ruta declara `response_model`** y las de escritura reciben
`payload: dict = Body(...)`. Devuelven el dict de TinyDB tal cual: hoy no hay campos sensibles
guardados, pero cualquier campo que se añada a la tabla saldría automáticamente al cliente, y
`/docs` no documenta ni la entrada ni la salida.

Nota importante sobre la entrada: la validación la hace `packages/shared/incident_model.py`
(`validate_incident_fields`, `validate_status_transition`), que **ya filtra** a los campos
escribibles (`title`, `description`, `category`, `origin`, `branch`, `status`; ignora `id`,
`created_at`, `updated_at`) y produce errores 400 con `{field, code}` que el frontend traduce
(`lib/incidents.ts` → `fieldErrorMessage`). Ver «Casos dudosos» para cómo encajar el esquema
Pydantic de entrada sin romper ese contrato.

## POST /api/incidents
- Propósito: registrar una incidencia.
- Consumidor y campos que usa: `app/(protected)/incidents/new/incident-form-client.tsx` → lee `created.id`. Envía `IncidentDraft` = `{title, description, category, status, origin, branch}`.
- Estado original: ❌ sin `response_model`, entrada `dict`.
- Esquema de entrada: `IncidentCreate` → `title`, `description`, `category`, `origin`, `branch`, `status` (opcional, por defecto `open`).
- Esquema de salida objetivo: `IncidentRead` → `id`, `title`, `description`, `category`, `status`, `origin`, `branch`, `created_at`, `updated_at` (es el recurso recién creado; el test `test_create_incident` fija exactamente estos 9 campos).
- Decisión sobre relaciones: no hay relaciones; `branch` es un código plano.
- Cambios aplicados: nuevo módulo `services/api/incident_models.py` con `IncidentCreate` (entrada, documental) e `IncidentRead`; `response_model=IncidentRead`. Entrada documentada en OpenAPI con `openapi_extra=json_body(...)`; la validación sigue en `validate_incident_fields` / `validate_status_transition` (sin cambios en códigos ni mensajes de error). Verificado: un `id`/`created_at` enviado por el cliente se ignora.
- Estado final: ✅

## GET /api/incidents
- Propósito: listado filtrable, más recientes primero.
- Consumidor y campos que usa: `incidents-manager-client.tsx` → `id`, `title`, `description` (fila expandida), `category`, `status`, `origin`, `branch`, `created_at`. **No lee `updated_at`.**
- Estado original: ❌ sin `response_model`.
- Esquema de salida objetivo: `list[IncidentListItem]` → `id`, `title`, `description`, `category`, `status`, `origin`, `branch`, `created_at`.
- Decisión sobre relaciones: no aplica.
- Cambios aplicados: `response_model=list[IncidentListItem]` (sin `updated_at`). Test `test_seed_applies_csv_to_model_transformations` lee ahora `updated_at` de la base de datos y además comprueba que el listado no lo expone.
- Estado final: ✅

## GET /api/incidents/summary
- Propósito: contadores totales y por estado/categoría/origen/sede.
- Consumidor y campos que usa: `incidents-manager-client.tsx` → `total`, `by_status`, `by_category`, `by_origin`, `by_branch`.
- Estado original: ❌ dict sin tipar.
- Esquema de salida objetivo: `IncidentSummary` → `total: int` y cuatro `dict[str, int]`.
- Decisión sobre relaciones: no aplica.
- Cambios aplicados: `response_model=IncidentSummary`.
- Estado final: ✅

## GET /api/incidents/search
- Propósito: búsqueda semántica con los mismos filtros que el listado.
- Consumidor y campos que usa: `incidents-manager-client.tsx` (misma tabla que el listado) → campos del listado + `score`. **No lee `possible_duplicate` ni `updated_at`.**
- Estado original: ❌ lista de dicts: incidencia completa + `score` + `possible_duplicate`.
- Esquema de salida objetivo: `list[IncidentSearchResult]` → campos de `IncidentListItem` + `score`.
- Decisión sobre relaciones: no aplica.
- Cambios aplicados: `response_model=list[IncidentSearchResult]` (listado + `score`, sin `possible_duplicate` ni `updated_at`).
- Estado final: ✅

## GET /api/incidents/semantic-status
- Propósito: estado de la capa de embeddings (diagnóstico).
- Consumidor y campos que usa: `incidents-manager-client.tsx` → solo `degraded`.
- Estado original: ❌ dict sin tipar → `provider`, `degraded`, `indexed`, `pending`.
- Esquema de salida objetivo: `SemanticStatus` → `provider`, `degraded`, `indexed`, `pending` (ver «Casos dudosos»).
- Decisión sobre relaciones: no aplica.
- Cambios aplicados: `response_model=SemanticStatus` con los 4 campos (propuesta 4: endpoint de diagnóstico).
- Estado final: ✅

## GET /api/incidents/duplicates
- Propósito: grupos de incidencias activas que parecen el mismo problema.
- Consumidor y campos que usa: `incidents-manager-client.tsx` → `size`, `title`, `category`, `branches`, `incident_ids`. **No lee `origins`.**
- Estado original: ❌ lista de dicts sin tipar.
- Esquema de salida objetivo: `list[DuplicateGroup]` → `size`, `title`, `category`, `branches`, `incident_ids`.
- Decisión sobre relaciones: **solo IDs** (`incident_ids`): el front solo los muestra/enlaza; anidar las incidencias completas multiplicaría el payload.
- Cambios aplicados: `response_model=list[DuplicateGroup]` (sin `origins`).
- Estado final: ✅

## POST /api/incidents/suggest
- Propósito: para un borrador, incidencias parecidas y categoría sugerida.
- Consumidor y campos que usa: `incident-form-client.tsx` → `similar[].id/title/status/branch/possible_duplicate`, `suggested_category.value/confidence`. Envía `{title, description}`.
- Estado original: ❌ entrada `dict`, salida dict sin tipar (cada similar es la incidencia completa, con `description` de hasta 5000 caracteres).
- Esquema de entrada: `IncidentSuggestRequest` → `title`, `description` (ambos opcionales; al menos uno no vacío).
- Esquema de salida objetivo: `IncidentSuggestion` → `similar: list[SimilarIncident]`, `suggested_category: CategorySuggestion | null` (`value`, `confidence`).
- Decisión sobre relaciones: proyección reducida `SimilarIncident` (ver `/similar`), compartida porque el tipo TS `SimilarIncident` es el mismo para ambas pantallas.
- Cambios aplicados: `response_model=IncidentSuggestion` con `similar: list[SimilarIncident]` y `CategorySuggestion`; entrada `IncidentSuggestRequest` documentada. Entrada documentada en OpenAPI con `openapi_extra=json_body(...)`; la validación sigue en `validate_incident_fields` / `validate_status_transition` (sin cambios en códigos ni mensajes de error).
- Estado final: ✅

## GET /api/incidents/{incident_id}
- Propósito: detalle de una incidencia.
- Consumidor y campos que usa: **sin consumidor** en el backoffice (`incidentsApi` no tiene `get`).
- Estado original: ❌ dict sin tipar.
- Esquema de salida objetivo: `IncidentRead` (detalle completo, 9 campos).
- Decisión sobre relaciones: no aplica.
- Cambios aplicados: `response_model=IncidentRead`.
- Estado final: ✅

## GET /api/incidents/{incident_id}/similar
- Propósito: casos pasados parecidos a una incidencia.
- Consumidor y campos que usa: `incidents-manager-client.tsx` (`SimilarRow`) → `id`, `title`, `status`, `branch`, `created_at`, `score`. Tipo TS `SimilarIncident` = `id, title, status, branch, created_at, category, score, possible_duplicate`.
- Estado original: ❌ lista de incidencias completas + `score` + `possible_duplicate`.
- Esquema de salida objetivo: `list[SimilarIncident]` → `id`, `title`, `category`, `status`, `branch`, `created_at`, `score`, `possible_duplicate`. Sin `description`, `origin`, `updated_at`.
- Decisión sobre relaciones: proyección plana reducida.
- Cambios aplicados: `response_model=list[SimilarIncident]` (sin `description`, `origin`, `updated_at`).
- Estado final: ✅

## PATCH /api/incidents/{incident_id}/status
- Propósito: avanzar el estado según el ciclo de vida.
- Consumidor y campos que usa: `incidents-manager-client.tsx` → `updated.id`, `updated.status`, y fusiona la respuesta en la fila (`{...item, ...updated}`). Envía `{status}`.
- Estado original: ❌ entrada `dict`, salida dict sin tipar.
- Esquema de entrada: `IncidentStatusUpdate` → `status`. Campos extra se ignoran (comportamiento cubierto por `test_extra_fields_in_the_body_are_ignored`).
- Esquema de salida objetivo: `IncidentRead` (el recurso actualizado completo; tests HTTP comprueban `updated_at`).
- Decisión sobre relaciones: no aplica.
- Cambios aplicados: `response_model=IncidentRead`; entrada `IncidentStatusUpdate` documentada. Entrada documentada en OpenAPI con `openapi_extra=json_body(...)`; la validación sigue en `validate_incident_fields` / `validate_status_transition` (sin cambios en códigos ni mensajes de error).
- Estado final: ✅

---

# Inventario (todas las rutas requieren JWT)

Ya seguía buenas prácticas: esquemas en `services/schemas.py` separados del ORM, entradas con
`extra="forbid"` y un test (`test_inventory_architecture.py`) que impide devolver modelos SQLModel.

## GET /inventory/products
- Propósito: SKUs con stock calculado.
- Consumidor y campos que usa: `inventory/products/products-client.tsx` → `id`, `sku`, `name`, `client_name`, `category`, `warehouse`, `current_stock`, `stock_by_warehouse` (todos). También alimenta los selectores de entrada/salida.
- Estado original: ✅ `list[SKURead]`.
- Esquema de salida objetivo: `list[SKURead]` (excepción justificada: el consumidor usa todos los campos; el front sustituye elementos de la lista por la respuesta del detalle).
- Decisión sobre relaciones: los movimientos **no** se anidan; el stock se resume en dos campos calculados.
- Cambios aplicados: ninguno; ya cumplía. Se revisó que el `response_model` existente coincide con el consumidor.
- Estado final: ✅

## POST /inventory/products
- Propósito: alta de SKU.
- Consumidor y campos que usa: sin consumidor en el backoffice.
- Estado original: ✅ entrada `SKUCreate` (`extra="forbid"`), salida `SKURead`.
- Esquema de entrada: `SKUCreate` → `name`, `sku`, `client_name`, `category`, `warehouse`.
- Esquema de salida objetivo: `SKURead`.
- Decisión sobre relaciones: no aplica.
- Cambios aplicados: ninguno; ya cumplía. Se revisó que el `response_model` existente coincide con el consumidor.
- Estado final: ✅

## GET /inventory/products/{sku_id}
- Propósito: un SKU con su stock.
- Consumidor y campos que usa: `outbound-client.tsx` → `stock_by_warehouse`, y reemplaza el SKU en la lista (necesita todos los campos).
- Estado original: ✅ `SKURead`.
- Esquema de salida objetivo: `SKURead`.
- Decisión sobre relaciones: no aplica.
- Cambios aplicados: ninguno; ya cumplía. Se revisó que el `response_model` existente coincide con el consumidor.
- Estado final: ✅

## POST /inventory/orders/inbound · POST /inventory/orders/outbound
- Propósito: registrar entrada / salida de stock.
- Consumidor y campos que usa: `inbound-client.tsx` → `quantity`, `sku.sku`, `sku.name`; `outbound-client.tsx` → `exit_type`, `quantity`, `tracking_number`, `warehouse`, `sku_id` (para pedir el stock actualizado), `sku.sku`, `sku.name`. El front envía exactamente los campos de `StockEntryCreate` / `StockExitCreate` (compatible con `extra="forbid"`).
- Estado original: ✅ entrada `StockEntryCreate`/`StockExitCreate` (`extra="forbid"`; sin `user_uuid`, que sale del token), salida `StockEntryRead`/`StockExitRead`.
- Esquema de salida objetivo: sin cambios.
- Decisión sobre relaciones: SKU anidado como `SKUSummary` (proyección sin stock).
- Cambios aplicados: ninguno; ya cumplía. Se revisó que el `response_model` existente coincide con el consumidor.
- Estado final: ✅

## GET /inventory/orders
- Propósito: histórico de movimientos (entradas y salidas mezcladas).
- Consumidor y campos que usa: `inventory/orders/orders-client.tsx` → `id`, `order_type`, `created_at`, `quantity`, `warehouse`, `reference`, `exit_type`, `tracking_number`, `user_uuid` (para «Tú»), `sku.sku`, `sku.name`, `sku.client_name`. **No lee** `sku_id`, `sku.id`, `sku.category`, `sku.warehouse`.
- Estado original: ⚠️ reutiliza los esquemas de detalle de creación: cada fila lleva la FK `sku_id` **y** el objeto `sku` con el mismo id, más `category`/`warehouse` del SKU que la tabla no usa.
- Esquema de salida objetivo: `list[StockOrderListItem]` (unión discriminada por `order_type`) → `id`, `order_type`, `quantity`, `warehouse`, `created_at`, `user_uuid`, `sku: SKURef` (`sku`, `name`, `client_name`) + `reference` (entrada) o `exit_type`, `tracking_number` (salida).
- Decisión sobre relaciones: **proyección anidada reducida** (`sku.sku`, `sku.name`, `sku.client_name`). La regla general preferiría campos planos (`sku_code`, `sku_name`…), pero el front lee `order.sku.sku`; aplanar rompería la pantalla. Se elimina la FK `sku_id` porque el objeto ya identifica al SKU.
- Cambios aplicados: en `services/schemas.py`: `SKURef`, `StockEntryListItem`, `StockExitListItem` y la unión `StockOrderListItem` (discriminada por `order_type`); se elimina `StockOrderRead`, que solo usaba esta ruta. `services/routers/inventory.py` devuelve los nuevos esquemas. `tests/inventory/test_inventory_orders.py` apunta a los nuevos tipos (mismas comprobaciones).
- Estado final: ✅

---

# Rutas de `main.py`

## GET /
- Propósito: mensaje de bienvenida / comprobación rápida.
- Consumidor y campos que usa: ninguno (healthcheck manual).
- Estado original: ❌ dict sin tipar.
- Esquema de salida objetivo: `MessageResponse` → `message` (reutilizado: contrato idéntico).
- Cambios aplicados: `response_model=MessageResponse`.
- Estado final: ✅

## POST /analyze
- Propósito: analizar un CSV de incidencias subido como archivo.
- Consumidor y campos que usa: `app/(protected)/analyzer-client.tsx` → `valid`, `invalid`, `categories`, `statuses`, `media_satisfaccion`, `errores[].incident_id`, `errores[].errors`. Envía `multipart/form-data` con `file`.
- Estado original: ❌ dict sin tipar.
- Esquema de entrada: `UploadFile` (multipart, campo `file`). No aplica esquema JSON.
- Esquema de salida objetivo: `AnalysisResult` → `valid: int`, `invalid: int`, `categories: dict[str,int]`, `statuses: dict[str,int]`, `media_satisfaccion: float`, `errores: list[AnalysisRowErrors]` (`incident_id: str`, `errors: list[str]`). Se mantienen los nombres en español: el front y los tests golden dependen de ellos.
- Decisión sobre relaciones: no aplica.
- Cambios aplicados: nuevo `services/api/analysis_models.py` (`AnalysisResult`, `AnalysisRowErrors`) y `response_model=AnalysisResult`. `incident_id` es `str | None`: `csv.DictReader` devuelve `None` si a una fila le falta la columna, y con `str` eso sería un 500.
- Estado final: ✅

## GET /api/incidents/results/export
- Propósito: descargar el último análisis como CSV.
- Consumidor y campos que usa: `analyzer-client.tsx` → descarga el blob.
- Estado original: ⚠️ devuelve un `Response` `text/csv` (correcto: no es JSON, `response_model` no aplica), pero OpenAPI lo documenta como `application/json` sin esquema.
- Esquema de salida objetivo: `response_class=Response` + `responses={200: {"content": {"text/csv": {...}}}}` para que `/docs` documente un CSV.
- Cambios aplicados: `response_class=Response` y `responses={200: {content: text/csv}}`: `/docs` ya lo muestra como descarga CSV.
- Estado final: ✅
- Observación fuera de alcance: `last_analysis` es una variable global compartida por todos los usuarios (un usuario puede exportar el análisis de otro). No es serialización; lo dejo anotado.

---

# Casos dudosos (resueltos: las 6 propuestas confirmadas)

1. **Registro devuelve email (`POST /users`)** — la regla exige quitarlo, pero `tests/test_auth.py::test_register_creates_user_with_default_role_and_linked_profile` lo afirma por HTTP (y `profile.user_id`). Mi análisis: el test congela un comportamiento inseguro, no una necesidad del cliente (el front ignora el cuerpo). Propuesta: cambiar esas dos aserciones por `assert "email" not in body` y comprobar el perfil por sus campos. No es debilitar el test: pasa a verificar la propiedad de seguridad.
2. **Entrada de incidencias** — si cambio `payload: dict` por un modelo Pydantic tipado (`title: str`), un `title: 123` lo rechazaría FastAPI antes del handler con el código `invalid_value`, en vez del `invalid_type` actual: rompe tests y los mensajes del front. Propuesta: definir los esquemas `IncidentCreate`, `IncidentStatusUpdate`, `IncidentSuggestRequest` y publicarlos en OpenAPI (`openapi_extra`), dejando `validate_incident_fields` (compartida con el seed) como única autoridad de validación. El filtrado de campos escribibles ya lo hace esa función.
3. **Recortes que no rompen el front pero quitan datos**: `origins` en `/duplicates`, `possible_duplicate` en `/search`, `updated_at` en el listado de incidencias. Los tests que los comprueban llaman a la función directamente (sin pasar por `response_model`), así que siguen pasando. ¿Los recorto según la regla «solo lo que usa el consumidor»?
4. **`/semantic-status`** — el front solo lee `degraded`. Propongo mantener los 4 campos: es un endpoint de diagnóstico y `provider/indexed/pending` son justo su razón de ser.
5. **`GET /inventory/orders`** — nuevo esquema de listado. `tests/inventory/test_inventory_orders.py::test_each_order_type_validates_against_the_union_schema` valida la salida contra `StockOrderRead`; habría que apuntarlo al nuevo `StockOrderListItem` (misma comprobación, nuevo tipo).
6. **`GET /users`** — sin consumidor; propongo `UserListItem` sin `created_at`.

---

# Verificación (Fase 3)

| Comprobación | Resultado |
|---|---|
| Tests antes (línea base) | 773 passed |
| Tests después | **773 passed**, 0 fallos |
| Peticiones reales (TestClient) | registro, login, `/auth/me`, forgot-password, alta de incidencia, listado/búsqueda/similares/duplicados/cambio de estado de incidencias, entrada de stock y listado de movimientos: el JSON coincide campo a campo con el esquema y no aparece ningún campo sensible (`password`, `hashed_password`, `email` en registro/login, `user_id`, `sku_id` en el listado…) |
| Asignación masiva | `POST /api/incidents` con `id: 999` y `created_at` → ignorados; `POST /users` con `role: admin` → `role: user` |
| `/openapi.json` | 40 operaciones; todas declaran esquema de respuesta (JSON con schema, o `text/csv` en la exportación). Todas las entradas JSON tienen esquema |

# Cambios que afectan al frontend

Ninguno rompe el backoffice en ejecución (todos los campos eliminados no se leen). Ajustes de
**tipos TypeScript** recomendados para que los tipos describan la respuesta real:

- `uis/backoffice/app/lib/types.ts` → `Me.profile`: `Pick<Profile, "name" | "phone" | "address"> | null`.
- `uis/backoffice/app/lib/inventory.ts` → `InventoryOrder` del listado: sin `sku_id`; `sku` con `sku`, `name`, `client_name` (la respuesta de los altas sí mantiene `sku_id` y `sku.id`).
- `uis/backoffice/app/lib/incidents.ts` → `Incident` del listado sin `updated_at`; `DuplicateGroup` ya no declaraba `origins`.
