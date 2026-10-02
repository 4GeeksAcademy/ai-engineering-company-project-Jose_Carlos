# Baseline de UIs (U-A5)

Comprobaciones repetibles del comportamiento **AS-IS** de las tres UIs de TrackFlow, derivadas de los
arneses de la auditoría R4 (`audit/evidence/dynamic/r4c/c3`, `r4b`, `r4d`). Su objetivo es detectar
regresiones durante las fases B y C del plan R7 (`audit/05-migration-refactoring-plan.md`): **no**
describen el comportamiento deseado, y no se corrige nada.

Junto con los tests de caracterización del backend (`tests/test_api_characterization.py`) forman la red
de seguridad de la Fase A.

## Requisitos

| Herramienta | Uso |
|---|---|
| Node.js ≥ 22 | ejecuta el arnés (usa `fetch` y `WebSocket` nativos; **sin dependencias npm**) |
| Google Chrome / Chromium instalado | navegador headless dirigido por el protocolo DevTools. Si no está en la ruta estándar: `CHROME_PATH=<ruta>` |
| `uv` | entorno Python del proyecto (la suite backoffice arranca la API con `.venv`; otra ruta: `PYTHON=<python>`) |
| `npm` | dependencias del tracker, solo desde su lockfile (`npm ci`) |
| Red | website: `cdn.tailwindcss.com`, `images.unsplash.com`; backoffice: `cdn.tailwindcss.com`; talent: `playground.4geeks.com` (solo lectura) |

## Comandos

Desde la raíz del repositorio, en un entorno limpio:

```sh
# 1. Entorno (una vez)
uv sync --frozen
npm ci --prefix uis/talent-pipeline-tracker --ignore-scripts --no-audit --no-fund

# 2. Backend: caracterización (24 tests)
uv run --frozen pytest

# 3. UIs: baseline (website + backoffice + talent)
node tests/ui/run.mjs

# Suites sueltas
node tests/ui/run.mjs website
node tests/ui/run.mjs backoffice
node tests/ui/run.mjs talent

# 4. Referencia U-A4: dataset real (csv/incidents-trackflow.csv) por el backoffice montado en FastAPI,
#    comparado con el golden R4-B (tests/golden/analyzer_incidents_trackflow.r4b.json). Fuera de run.mjs.
node tests/ui/ua4_dataset_reference.mjs
```

`run.mjs` termina con código 0 solo si pasan todas las comprobaciones. Imprime una línea `PASS`/`FAIL` por
comprobación y un resumen. **No escribe ningún fichero en el repositorio**: ni informes, ni capturas, ni logs.

Cada suite arranca y detiene sus propios procesos (servidor estático en Node, `uvicorn`, `next dev`, Chrome
headless) en `127.0.0.1` con puertos efímeros, y borra sus directorios temporales (perfil de Chrome, CSV
sintéticos, TEMP de la API). Ante Ctrl+C, un error o un timeout global de 20 min, mata el árbol de
procesos. No hace falta tener nada arrancado antes.

## Qué se comprueba

Cada comprobación lleva un tipo:

- **baseline**: comportamiento conocido-bueno que debe sobrevivir a B y C.
- **as-is-quirk**: comportamiento actual ligado a un finding abierto. Una unidad posterior lo cambiará
  *a propósito* (C1/C3 para F-15, L1 para F-13…); al hacerlo, la comprobación se actualiza en esa unidad.

### Website (`website.mjs`) — BP-4, R4-C3

Se sirve `uis/` con un servidor estático de solo lectura (la misma raíz que R4).

| ID | Comprobación |
|---|---|
| WEB-01..03 | index.html carga, 0 excepciones, Tailwind aplicado (header `fixed`) |
| WEB-04..11 | marca, nav (≥3 enlaces visibles), carrusel (Slide 1 de 3, 3 puntos), imagen hero cargada, Beneficios (4), Sobre nosotros (3), Registro (2 inputs), CTA → `application.html`, dirección, footer |
| WEB-12..13 | `#mobileMenu` y `#loginPanel` ocultos; todo `.hidden` con `display:none` salvo override responsive |
| WEB-14 | sin overflow horizontal a 1280 px |
| WEB-15..17 | carrusel: siguiente → 2 → 3 → vuelve a 1 (etiqueta, punto activo, tag e imagen) |
| WEB-18 | registro vacío → error de validación visible, sin peticiones |
| WEB-19 | `application.html` resuelve (200) |
| WEB-M01..M06 | móvil 390×844: botón de menú visible, nav de escritorio oculta, menú abre/cierra con `aria-expanded`, sin overflow, todo `.hidden` oculto |
| APP-01..07 | application.html: carga, pestañas Particulares/Empresas, `businessForm` oculto, cambio de pestaña |
| *-NET | solo hosts de la allowlist, solo GET/HEAD, nada bloqueado |

Se comprueban invariantes semánticos (estructura, visibilidad, interacción), no textos comerciales: L2
cambiará el contenido sin romper estas comprobaciones.

### Backoffice (`backoffice.mjs`) — BP-3, R4-C3 + R4-B + modo FastAPI

Tres modos de servicio, como hoy:

| Prefijo | Modo | Comprobaciones clave |
|---|---|---|
| BO-OWN | estático, raíz `uis/backoffice/` | render (01–07), envío sin archivo → mensaje (09), selección de archivo (10), API inaccesible → "Failed to fetch" en pantalla (11–12); *quirk*: `ANALYZE_URL = http://localhost:8000/analyze`, enlace a la web → 404 (FM-R4-003) |
| BO-UIS | estático, raíz `uis/` | render; *quirk*: `ANALYZE_URL = /analyze` → POST al servidor estático → 405 en pantalla (FM-R4-005); enlace a la web → 200 |
| BO-API | montado en FastAPI (`uvicorn services.api.main:app`, `/backoffice/`) | render; error 500 (archivo no UTF-8) en pantalla; análisis de un CSV sintético → métricas 3/2/4.50, desgloses en orden de la API, 2 registros inválidos; exportar → GET `/api/incidents/results/export` 200 `text/csv` con el CSV esperado; *quirks*: enlace a la web → 404; `/analyze` deja un temporal por subida |

`http://localhost:8000` nunca se contacta (el guard lo bloquea). Los CSV subidos son sintéticos (las
mismas 5 filas que los tests del backend). `uvicorn` se ejecuta con `TEMP`/`TMP`/`TMPDIR` apuntando a un
directorio desechable (porque `/analyze` no borra su copia temporal) y con `PYTHONDONTWRITEBYTECODE=1`.
Las descargas se deniegan en el navegador.

### Talent Pipeline Tracker (`talent.mjs`) — BP-5, R4-D

Arranca `next dev` del propio tracker y lee la API externa **en vivo**, por lo que compara propiedades
contra las respuestas observadas, no valores fijos.

| ID | Comprobación (R4-D) |
|---|---|
| TAL-001-* | paginación: página 1 = respuesta, total y "Página 1 de N", recorrido completo con Siguiente, suma = total, ids distintos, Siguiente/Anterior deshabilitados en los extremos, sin recarga |
| TAL-002-* | filtro por estado (4 valores + "Todos"): GET con `status` y `page=1`, todas las tarjetas/ítems coinciden |
| TAL-003-* | filtro por etapa (5 valores), combinación estado + etapa, limpieza |
| TAL-004-* | búsqueda por nombre (sin distinguir mayúsculas), tecleo carácter a carácter, limpieza. **No** se busca por email (decisión de privacidad de R4-C1) |
| TAL-005-* | navegación al detalle correcto, GET solo de ese id, foto por la ruta local, volver al listado, id inexistente → 404 controlado |
| TAL-014-* | sin valores crudos de enum en listado, listado filtrado, detalle y formulario de alta (solo abrir/cerrar) |
| TAL-015-* | notas no visibles en el listado (aunque la respuesta las incluye, F-16), visibles y en orden en el detalle |
| TAL-SAFE-* | solo GET/HEAD a la API, ningún otro host, 0 excepciones |
| TAL-PRIVACY | la salida no contiene valores personales ni ids de registro (fail-closed) |

Las etiquetas esperadas son las **actuales** de `app/lib/constants.ts` ("Recibido", "Pendiente",
"Revisión"…). F-13 / U-L1 las cambiará deliberadamente; ese cambio debe actualizar `STATUS_LABELS` y
`STAGE_LABELS` en `talent.mjs`.

## Matriz de seguridad

| Comprobación | UI | Red | Solo lectura | Muta estado local | Muta estado externo | Automatizada | Estrategia |
|---|---|---|---|---|---|---|---|
| Render, secciones, ocultos, carrusel, menú, pestañas | Website | CDN + Unsplash (GET) | sí | no | no | sí | servidor estático GET-only + guard CDP |
| Render en 2 raíces, envío sin archivo | Backoffice | CDN (GET) | sí | no | no | sí | ídem |
| API inaccesible / 405 | Backoffice | ninguna externa | sí | no | no | sí | `localhost:8000` bloqueado; CSV sintético |
| Análisis + export en modo montado | Backoffice | solo 127.0.0.1 | POST local | estado en memoria del proceso; temporales en TEMP desechable | no | sí | `uvicorn` efímero, TEMP aislado, descargas denegadas |
| Listado, paginación, filtros, búsqueda, detalle, 404, etiquetas, notas | Talent | API Talent (GET) | sí | `.next/` (ignorado por git) | no | sí | guard CDP: escrituras bloqueadas antes de salir |
| Alta, edición, estado/etapa, notas, borrado, fotos (TALENT-006..011) | Talent | — | **no** | — | **sí** | **no** | excluido: no es comportamiento conocido-bueno |

Guard del tracker: `127.0.0.1` solo GET/HEAD (no-GET solo para `/_next/*` y `/__nextjs*`);
`playground.4geeks.com` solo GET/HEAD (POST, PUT, PATCH, DELETE y OPTIONS se bloquean y hacen fallar
`TAL-SAFE-01`); cualquier otro host bloqueado; DNS desactivado para todo lo que no esté en la allowlist.
Todas las llamadas a la API Talent salen del navegador (componentes cliente), así que el guard las ve todas.

## Privacidad

- Los cuerpos de la API Talent solo viven en memoria para compararlos con el DOM.
- Los detalles impresos se limitan a recuentos, booleanos, etiquetas de enum y plantillas de ruta
  (`/records/{id}`). Antes de imprimirse se redactan contra todos los valores personales vistos y los UUID,
  y `TAL-PRIVACY` falla si quedara alguno.
- Sin capturas de pantalla. La salida de `next dev` se queda en memoria y solo se muestra, con los UUID
  redactados, si el servidor no llega a arrancar.

## Limitaciones conocidas

- Website y backoffice dependen del CDN de Tailwind y de Unsplash en tiempo de ejecución (F-14). Sin red,
  fallan las comprobaciones de estilo y visibilidad: es el comportamiento AS-IS de FM-R4-001/002, no un
  fallo del arnés.
- Talent depende de la disponibilidad y del contenido de una API compartida. Si alguien la modifica durante
  la ejecución, alguna comprobación de sincronización podría fallar de forma transitoria: hay que repetirla
  antes de diagnosticar una regresión.
- La comparación visual píxel a píxel no se automatiza. Las capturas de referencia de R4-C3 siguen en
  `audit/evidence/dynamic/r4c/c3/` (hoy `audit/` está en `.gitignore` por un cambio local previo).
