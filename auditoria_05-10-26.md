# Auditoría de gestión de errores — TrackFlow

**Fecha:** 2026-10-05 · **Tipo:** revisión estática de código (realizado los cambios el día 2026-10-05).

## Alcance

- **Revisado:** `services/api/`, `scripts/`, `packages/shared/`, `uis/backoffice/`, `uis/talent-pipeline-tracker/app/`, `uis/website/`, `src/`, `skills/data-analysis/scripts/`.
- **Incluye** el gestor de incidencias todavía sin subir (`routes/incidents.py`, `incident_service.py`, `embeddings.py`, `seed_incidents.py`, `incidents*.js`, `incident-new.*`).
- **Fuera de alcance:** `tests/`, `node_modules/`, `.venv/`, `audit/`, y las carpetas que solo contienen README (`agents/`, `workflows/`, `mcps/`, `infra/`, `data/`, `internal/`, `shared/`).

## Categorías

| Nº | Categoría |
| --- | --- |
| 1 | Try/catch ausente |
| 2 | Catch demasiado amplio |
| 3 | Fallos silenciosos |
| 4 | Exposición de errores en crudo |
| 5 | Filtración de datos sensibles |
| 6 | Estados de carga/error ausentes en la UI |
| 7 | Sin llamada a la acción para el usuario |
| 8 | Sin `sys.exit` en fallo de script |

## Resumen

| Severidad | Hallazgos |
| --- | --- |
| CRÍTICO | 0 |
| ALTO | 6 |
| MEDIO | 17 |
| BAJO | 17 |

No hay hallazgos críticos: ningún endpoint devuelve stack traces, ninguna respuesta incluye secretos y no hay bloques `except: pass`. Los problemas más serios son la filtración de datos a logs y a disco, y los mensajes técnicos que llegan al usuario en dos de las tres interfaces.

Patrones que se repiten:

- **Mensajes en crudo en el frontend.** El backoffice antiguo (analizador, proveedores, login) y toda la app Next.js muestran `error.message`, códigos HTTP o el `detail` del servidor tal cual. Solo las pantallas del gestor de incidencias traducen los errores.
- **Errores sin salida.** Varias pantallas muestran el fallo pero no ofrecen reintentar.
- **Sin tiempo de espera.** Ningún `fetch` del repositorio tiene timeout: si el servidor no responde, el indicador de carga no termina nunca.
- **Scripts sin código de salida explícito.** Ningún script captura sus errores críticos; salen con traceback, y los fallos parciales terminan con código 0.

---

## ALTO

| ID | Ubicación | Cat. | Problema | Corrección sugerida |
| --- | --- | --- | --- | --- |
| A1 | `services/api/email_service.py:103-106` | 5 | Si `RESEND_API_KEY` está vacía (valor por defecto), el enlace de restablecimiento completo, con su token, y el email del usuario se escriben en el log. Nada limita esto a desarrollo: quien lea los logs puede cambiar la contraseña de esa cuenta. | Registrar el enlace solo con un indicador explícito de desarrollo; en cualquier otro caso registrar que falta la clave, sin token ni email. |
| A2 | `services/api/main.py:80-91` | 1, 5 | `POST /analyze` no tiene manejo de errores y crea el temporal con `delete=False` sin borrarlo nunca. Cada CSV subido (con emails de clientes) queda en el directorio temporal, también cuando el análisis falla. | Envolver el análisis en `try/finally` que borre el temporal; responder 400 con mensaje claro si el archivo no es UTF-8 o no es un CSV válido. |
| A3 | `uis/talent-pipeline-tracker/app/api/profile-photo/[recordId]/route.ts:46-54, 77-85` | 4, 5 | La respuesta 500 devuelve `error.message` de `fs`, que incluye la ruta absoluta del servidor (`ENOENT: ... open 'C:\...\imagenesPerfil\...'`). | Devolver un mensaje fijo y registrar el detalle solo en el servidor. |
| A4 | `uis/talent-pipeline-tracker/app/api/upload-photo/route.ts:10-45` | 1 | Ninguna operación (`formData()`, `mkdir`, `readdir`, `unlink`, `writeFile`) tiene manejo de errores. Un cuerpo mal formado o un fallo de disco produce un 500 sin control, y si falla tras el `unlink` la foto anterior ya se ha borrado. | Capturar por operación: 400 si el cuerpo no es un formulario válido, 500 genérico si falla el disco; escribir la foto nueva antes de borrar la anterior. |
| A5 | `uis/talent-pipeline-tracker/app/lib/api.ts:27-33, 114-116, 143-145` y sus usos en `app/ui/home-client.tsx:119, 186, 341, 372` y `app/(protected)/records/[id]/record-detail-client.tsx:112, 126, 152, 176, 194, 217, 224, 280, 299, 348, 449, 599` | 1, 4 | Las diez funciones de la API lanzan `Error ${status}: ${statusText}` y no capturan fallos de red; las pantallas pintan `error.message` tal cual. El usuario ve "Error 404: Not Found" o "Failed to fetch". | Lanzar un error tipado (red, no encontrado, validación, servidor) y traducirlo a un mensaje propio en la pantalla, como ya hace `lib/auth.ts` con `ApiError`. |
| A6 | `uis/backoffice/app.js:188-194, 270-275, 301-306` | 4 | El analizador muestra `body.detail` del servidor, el código de estado ("El servidor respondió con el estado 500") o el mensaje del navegador ("Failed to fetch"). Si `detail` es una lista (422) se pinta `[object Object]`. | Elegir el mensaje en el cliente según el tipo de fallo (sin conexión, archivo no válido, error del servidor) y no mostrar nunca el texto recibido. |

---

## MEDIO

| ID | Ubicación | Cat. | Problema | Corrección sugerida |
| --- | --- | --- | --- | --- |
| M1 | `uis/backoffice/suppliers.js:67-85, 268, 304, 367, 449` | 4 | `formatApiError` enseña los mensajes de validación de FastAPI en inglés técnico ("rate_per_shipment: Input should be greater than 0") y "Error 500 en la API.". | Mapear campo y tipo de error a textos propios; mensaje genérico para 5xx. |
| M2 | `uis/backoffice/suppliers.js:358-371` | 7 | Si falla la carga del listado se vacía la tabla y se muestra el error, sin botón para reintentar; hay que recargar o tocar un filtro. | Añadir un botón "Reintentar" que llame a `loadSuppliers()`. |
| M3 | `uis/backoffice/login.html:86-96` | 4 | Muestra `Error ${status} en la API.` y, si la respuesta 200 no es JSON, el `SyntaxError` del navegador. Detecta el fallo de red comprobando `TypeError`, que también captura errores de programación. | Separar el `fetch` (fallo de red) del resto; mensaje genérico para cualquier otro caso. |
| M4 | `uis/talent-pipeline-tracker/app/ui/home-client.tsx:370-374` | 7 | El error del listado de candidaturas no ofrece reintentar, aunque ya existe `refreshTick` para recargar. | Botón "Reintentar" que incremente `refreshTick`. |
| M5 | `uis/talent-pipeline-tracker/app/(protected)/records/[id]/record-detail-client.tsx:346-350` | 6, 7 | Un único aviso "Ocurrió un error" sirve para la carga y para todas las acciones (cambiar estado, subir foto, borrar). No distingue "la candidatura no existe" de un fallo temporal, no ofrece reintentar y no se limpia hasta la siguiente acción correcta. | Estado propio para "no encontrada" y para "fallo de carga" con reintento; errores de acción junto al control que los provoca. |
| M6 | `uis/talent-pipeline-tracker/app/(protected)/records/[id]/record-detail-client.tsx:191-195, 597-601` | 4 | Si falla borrar o crear una nota, el error se guarda en `notesState.error` y se muestra como "No se pudieron cargar las notas", que no es lo que ha pasado. | Estado de error separado para las acciones sobre notas. |
| M7 | `uis/talent-pipeline-tracker/app/` (no existen `error.tsx`, `global-error.tsx` ni `not-found.tsx`) | 6 | Una excepción durante el render deja la pantalla de error por defecto de Next, sin navegación ni reintento. | Añadir `error.tsx` con botón de reintento y `not-found.tsx` con enlace al listado. |
| M8 | Todos los `fetch`: `uis/backoffice/auth.js:90-108`, `uis/backoffice/incidents-common.js:409-427`, `uis/talent-pipeline-tracker/app/lib/api.ts`, `app/lib/auth.ts:139-145` | 6 | Ninguna petición tiene tiempo de espera. Si el servidor acepta la conexión y no responde, los indicadores de carga y los botones deshabilitados quedan así indefinidamente. | `AbortController` con timeout y tratarlo como fallo de red. |
| M9 | `uis/backoffice/incidents-common.js:422` con `uis/backoffice/incidents.js:427-441` | 1 | Una respuesta 200 que no sea JSON devuelve `null`. En el listado, `renderList()` se ejecuta fuera del `try` y falla con `incidents.length`: la página queda con el indicador de carga y sin mensaje. | Tratar el cuerpo no válido como error de servidor dentro de `request()`. |
| M10 | `services/api/embeddings.py:93-99` | 2, 3 | Si el modelo no carga, cualquier excepción se registra y se cambia al proveedor por hashing durante toda la vida del proceso. La búsqueda sigue respondiendo con peor calidad y nada lo indica al cliente ni lo reintenta. | Capturar solo los errores de carga esperados, exponer el proveedor activo (cabecera o endpoint de estado) y reintentar pasado un tiempo. |
| M11 | `services/api/routes/incidents.py:142-143` con `services/api/embeddings.py:84-101` | 1 | `POST /api/incidents` calcula el embedding dentro de la petición. La primera vez carga el modelo (o lo descarga, ~220 MB) sin límite de tiempo: el alta se queda esperando. | Indexar en segundo plano (`BackgroundTasks`) o cargar el modelo al arrancar. |
| M12 | `services/api/routes/incidents.py:117-126` | 2 | `_semantic` convierte cualquier excepción en 503, también errores de programación (un `KeyError`, por ejemplo), que quedan disfrazados de "servicio no disponible". | Capturar solo los fallos del proveedor de embeddings; dejar que el resto llegue al manejador de 500. |
| M13 | `services/api/main.py:93-97` con `uis/backoffice/app.js:287-299` | 3 | Exportar sin análisis previo responde 200 con un mensaje JSON. Tras reiniciar el servidor el botón sigue activo y el usuario descarga un `results.csv` que contiene ese JSON. | Responder 404 o 409 y que la interfaz lo muestre como "no hay ningún análisis". |
| M14 | `services/api/main.py` (sin manejador global) | 4 | Solo las rutas de incidencias devuelven un 500 en JSON. El resto responde texto plano "Internal Server Error", que el backoffice convierte en "El servidor respondió con el estado 500". No se filtra el stack trace, pero el formato es inconsistente. | Un `exception_handler` global con el mismo cuerpo JSON que usa el gestor de incidencias. |
| M15 | `services/api/routes/auth.py:66-70` y `services/api/email_service.py:108-113` | 3 | El envío del correo de restablecimiento ignora el resultado de `send_email`. Si el proveedor falla, el usuario recibe "te llegará un enlace", el intento cuenta para el límite por hora y solo queda una línea en el log. | Registrar el fallo con un identificador que se pueda vigilar y no contar el intento fallido en el límite. |
| M16 | `services/api/create_admin.py:32-36` | 5 | Al fallar la validación se imprime la excepción de Pydantic, que incluye `input_value`; si lo no válido es la contraseña, queda escrita en la consola. | Imprimir solo campo y motivo (`exc.errors()` sin `input`). |
| M17 | `scripts/seed_incidents.py:37-70, 103` | 1, 8 | Un CSV con otra cabecera u otra codificación no se detecta: termina con 0 insertadas y código 0, o con traceback a mitad de carga dejando una inserción parcial y sin informe. | Comprobar la cabecera antes de empezar, capturar `UnicodeDecodeError`/`csv.Error` con mensaje claro y salir con código distinto de 0 si no se insertó ni se omitió ninguna fila. |

---

## BAJO

| ID | Ubicación | Cat. | Problema | Corrección sugerida |
| --- | --- | --- | --- | --- |
| B1 | `scripts/analyze.py:172-181` | 1, 8 | Sin manejo de errores: archivo inexistente o mal codificado termina en traceback, y `input()` lanza `EOFError` si se ejecuta sin terminal. No hay código de salida explícito. | `try/except` en el bloque principal con mensaje claro y `sys.exit(1)`; ruta y exportación por argumentos. |
| B2 | `scripts/analyze.py:138-163` | 1 | `exportResults` no captura fallos de escritura (archivo abierto en Excel, sin permisos). | Capturar `OSError` e informar de la ruta. |
| B3 | `scripts/seed_incidents.py:107-113` | 4, 8 | Si fallan los embeddings se imprime el mensaje de la excepción tal cual y el script termina con código 0. Es intencionado (la API los recalcula), pero un proceso automático no lo distingue de un éxito completo. | Mensaje propio y un código de salida diferenciado, o una opción `--strict`. |
| B4 | `services/api/seed.py:170-201` | 1, 8 | Sin manejo de errores ni código de salida explícito. Con `--force` se vacía la tabla antes de insertar: si una entrada falla, los proveedores quedan borrados o a medias. | Validar todo el seed antes de vaciar; `sys.exit(1)` con mensaje si algo falla. |
| B5 | `services/api/create_admin.py:26-30, 38-43` | 1, 8 | `update_user` y `create_user` sin capturar: un error de base de datos o un email duplicado termina en traceback. | Capturar `EmailAlreadyRegistered` y errores de almacenamiento con mensaje y `sys.exit(1)`. |
| B6 | `services/api/config.py:28, 35, 38` | 1 | `int(os.getenv(...))` sin validar: un valor no numérico en `.env` impide arrancar la API con un `ValueError` que no dice qué variable falla. | Función auxiliar que indique la variable y el valor esperado, como ya hace `_required`. |
| B7 | `services/api/store.py:16, 115` | 1 | TinyDB se abre al importar el módulo. Un `db.json` corrupto o bloqueado tira la API al arrancar con un traceback, sin mensaje sobre el archivo. | Capturar el error de apertura e indicar la ruta del archivo afectado. |
| B8 | `services/api/user_service.py:83-84` | 1 | Usuario y perfil se insertan en dos pasos. Si el segundo falla queda un usuario sin perfil y `/profiles/me` le responde 404 para siempre. | Deshacer la inserción del usuario si falla la del perfil. |
| B9 | `services/api/security.py:25-30` | 3 | `verify_password` devuelve `False` ante un hash corrupto sin registrarlo: no se distingue de una contraseña incorrecta. | Registrar un aviso (sin el hash ni la contraseña) cuando el hash no sea válido. |
| B10 | `services/api/routes/incidents.py:55-78` | 2 | El `try/except` envuelve la ruta completa. Es una frontera de errores deliberada, pero está implementada como clase de ruta propia en lugar de manejadores de la aplicación. | Sustituirla por `exception_handler` de la aplicación (ver M14). |
| B11 | `services/api/incident_service.py:70-75` | 3 | Si falla el indexado tras crear una incidencia solo se escribe en el log; la respuesta 201 no indica que la incidencia aún no aparece en búsquedas. | Incluir un indicador en la respuesta o un contador de incidencias pendientes de indexar. |
| B12 | `services/api/email_service.py:33-36` | 5 | El log de fallo de envío incluye la dirección de correo del destinatario. | Registrar el id de usuario en lugar del email. |
| B13 | Respuestas 422 por defecto en `/users`, `/auth/*`, `/suppliers` | 4 | El cuerpo de error de FastAPI incluye el campo `input` con el valor enviado; en `/users` y `/auth/*` puede ser la contraseña. Vuelve al mismo cliente que la envió, pero puede acabar en logs intermedios. | Manejador de `RequestValidationError` que omita `input`. |
| B14 | `uis/backoffice/auth.js:38-50` y `uis/talent-pipeline-tracker/app/lib/auth.ts:26-33` | 3 | Si `localStorage` no está disponible, `setToken` falla en silencio: el login parece correcto y el usuario vuelve a la pantalla de login sin explicación. | Avisar de que el navegador no permite guardar la sesión. |
| B15 | `uis/backoffice/incidents.js:202-210, 318-321` y `uis/backoffice/incident-new.js:283-288` | 3, 7 | El panel de duplicados y el de casos similares muestran el error sin botón de reintento. La ayuda del formulario ignora sus fallos por diseño, así que el usuario no sabe que no se comprobaron duplicados. | Botón de reintento en ambos paneles y un aviso discreto cuando la comprobación de duplicados no esté disponible. |
| B16 | `uis/talent-pipeline-tracker/app/lib/auth.ts:118-121, 136` y `app/(protected)/account/profile/page.tsx:100-104` | 4, 7 | Los errores de validación no previstos y los `detail` de texto del servidor se muestran en inglés tal cual. El error de carga del perfil no ofrece reintentar. | Mensaje genérico por defecto y botón de reintento en el perfil. |
| B17 | `src/index.html:263-265, 348-401`, `uis/website/trackflow-web/index.html:377`, `uis/website/trackflow-web/application.html:371, 416`, `skills/data-analysis/scripts/pandas_clean.py:8` | 2, 3, 4, 8 | Código de demostración: `src/index.html` muestra el mensaje de `JSON.parse` y envuelve manejadores enteros; los formularios de la web anuncian éxito con `alert` sin enviar nada; la plantilla de pandas no controla la lectura del archivo. | Mensajes propios en la demo; indicar en la web que el envío es simulado; `try/except` con `sys.exit(1)` en la plantilla. |

---

## Cobertura por archivo

| Archivo o módulo | Hallazgos |
| --- | --- |
| `services/api/main.py` | A2, M13, M14 |
| `services/api/email_service.py` | A1, M15, B12 |
| `services/api/embeddings.py` | M10, M11 |
| `services/api/routes/incidents.py` | M11, M12, B10 |
| `services/api/incident_service.py` | B11 |
| `services/api/routes/auth.py` | M15 |
| `services/api/create_admin.py` | M16, B5 |
| `services/api/seed.py` | B4 |
| `services/api/config.py` | B6 |
| `services/api/store.py` | B7 |
| `services/api/user_service.py` | B8 |
| `services/api/security.py` | B9 |
| `services/api/routes/users.py`, `routes/profiles.py`, `routes/suppliers.py` | B13 (formato 422 por defecto); sin más hallazgos |
| `services/api/models.py`, `user_models.py` | Sin hallazgos |
| `packages/shared/incident_model.py`, `incident_validation.py` | Sin hallazgos |
| `scripts/analyze.py` | B1, B2 |
| `scripts/seed_incidents.py` | M17, B3 |
| `uis/backoffice/app.js` | A6, M13 |
| `uis/backoffice/suppliers.js` | M1, M2 |
| `uis/backoffice/login.html` | M3 |
| `uis/backoffice/auth.js` | M8, B14 |
| `uis/backoffice/incidents-common.js`, `incidents.js`, `incident-new.js` | M8, M9, B15 |
| `uis/talent-pipeline-tracker/app/lib/api.ts` | A5, M8 |
| `uis/talent-pipeline-tracker/app/lib/auth.ts` | M8, B14, B16 |
| `uis/talent-pipeline-tracker/app/api/profile-photo/[recordId]/route.ts` | A3 |
| `uis/talent-pipeline-tracker/app/api/upload-photo/route.ts` | A4 |
| `uis/talent-pipeline-tracker/app/ui/home-client.tsx` | A5, M4 |
| `uis/talent-pipeline-tracker/app/(protected)/records/[id]/record-detail-client.tsx` | A5, M5, M6 |
| `uis/talent-pipeline-tracker/app/(protected)/account/profile/page.tsx` | B16 |
| `uis/talent-pipeline-tracker/app/` (estructura) | M7 |
| `uis/talent-pipeline-tracker/app/ui/auth-guard.tsx`, páginas de `(auth)/` y `account/change-password` | Sin hallazgos propios (heredan B16) |
| `uis/website/trackflow-web/*.html`, `src/index.html`, `skills/data-analysis/scripts/pandas_clean.py` | B17 |
| `src/utils/*.ts`, `src/types/models.ts`, `packages/shared/types/index.ts` | Sin hallazgos (funciones puras, sin E/S) |
