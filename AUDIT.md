# AUDIT.md — Auditoría de rendimiento de los dos frontends

Auditoría Lighthouse del **sitio corporativo** (`uis/website/trackflow-web`, HTML estático) y del
**backoffice** (`uis/backoffice`, Next.js 16). Recoge las puntuaciones iniciales, los problemas
encontrados y la causa raíz de cada uno. Las correcciones aplicadas y su impacto medido están en
[REPORT.md](REPORT.md); la explicación didáctica de todo el proceso, en [hito_11.md](hito_11.md).

Fecha: 20/10/2026.

## 1. Metodología

**Modo producción.** Las dos aplicaciones se auditaron como las recibiría un usuario real, nunca con
`npm run dev` (el modo desarrollo no minifica, carga React en modo desarrollo y compila cada página
en la primera visita, lo que falsea las métricas):

| App | Arranque | URL |
|---|---|---|
| Backend (necesario para el backoffice) | `docker compose up -d backend` | http://localhost:8000 |
| Backoffice | `npm run build` + `npm run start` en `uis/backoffice` | http://localhost:3001 |
| Sitio corporativo | servidor estático (`serve`) sobre `uis/website/trackflow-web` | http://localhost:3000 |

**Dos fuentes de medición:**

1. **Lighthouse en Chrome DevTools** (capturas de la auditoría), modo *Navigation*, ventana de
   incógnito, móvil y escritorio. Son las puntuaciones iniciales oficiales:
   [docs/lighthouse/capturas/antes](docs/lighthouse/capturas/antes).
2. **Lighthouse CLI con un script reproducible** ([tests/perf/lighthouse.mjs](tests/perf/lighthouse.mjs)).
   Repite cada medición en condiciones idénticas antes y después de los cambios, que es lo que
   recomiendan las skills (`performance` → *Repeatable lab comparisons*): 3 ejecuciones por caso,
   mediana por puntuación de Performance, caché HTTP vacía en cada ejecución, Chrome headless sin
   extensiones y una API local con base de datos desechable. Resumen:
   [docs/lighthouse/before/summary.json](docs/lighthouse/before/summary.json).

| Condición | Valor |
|---|---|
| Lighthouse | 13.5.0 (CLI) / el de Chrome DevTools en las capturas |
| Navegador | Chrome 155 headless |
| Móvil | Moto G Power emulado, *throttling* simulado: RTT 150 ms, 1,6 Mbps, CPU ×4 |
| Escritorio | `--preset=desktop` (RTT 40 ms, 10 Mbps, sin ralentizar CPU) |
| Páginas | web: `/` y `/application`; backoffice: `/login` y `/` (analizador, con sesión) |
| Sesión | cuenta sintética; usuario que vuelve (la vista se abre una vez y se mide la siguiente carga) |

Las skills instaladas para guiar el análisis y las correcciones son `core-web-vitals` y `performance`
(addyosmani/web-quality-skills) y `web-perf` (cloudflare/skills); están en `.agents/skills/`.

## 2. Puntuaciones iniciales

### 2.1 Capturas de Chrome DevTools (oficiales)

| Página | Dispositivo | Performance | Accessibility | Best Practices | SEO | FCP | LCP | TBT | CLS | SI |
|---|---|---|---|---|---|---|---|---|---|---|
| Web `/` | Móvil | **85** | **92** | 100 | 100 | 2,2 s | **3,9 s** | 0 ms | 0 | 2,2 s |
| Web `/` | Escritorio | 100 | **92** | 100 | 100 | 0,5 s | 0,8 s | 0 ms | 0 | 0,5 s |
| Backoffice `/` (analizador) | Móvil | **95** | 100 | 100 | 100 | 0,8 s | **2,9 s** | 60 ms | 0 | — |
| Backoffice `/` (analizador) | Escritorio | 100 | 100 | 100 | 100 | — | — | — | — | — |
| Backoffice `/login` | Móvil | **96** | 100 | 100 | 100 | 0,8 s | **2,7 s** | 120 ms | 0 | 0,8 s |
| Backoffice `/login` | Escritorio | 100 | 100 | 100 | 100 | — | — | — | — | — |

### 2.2 Lighthouse CLI (mediana de 3 ejecuciones, condiciones controladas)

Coinciden con las capturas (±1 punto), lo que valida el script como referencia para comparar.
Rango entre ejecuciones: idéntico en todos los casos salvo el analizador en móvil (Performance 91–95,
LCP 2,9–3,5 s).
Incluye además `/application`, que no tenía captura.

| Caso | Perf | A11y | BP | SEO | FCP | LCP | TBT | CLS | Peticiones | Transferido |
|---|---|---|---|---|---|---|---|---|---|---|
| Web `/` móvil | 86 | 92 | 100 | 100 | 2,1 s | 3,9 s | 0 ms | 0 | 4 | 472 KiB |
| Web `/` escritorio | 99 | 92 | 100 | 100 | 0,5 s | 0,8 s | 0 ms | 0 | 4 | 473 KiB |
| Web `/application` móvil | 97 | 89 | 100 | 100 | 2,1 s | 2,1 s | 0 ms | 0 | 3 | 129 KiB |
| Web `/application` escritorio | 100 | 89 | 100 | 100 | 0,5 s | 0,5 s | 0 ms | 0 | 3 | 129 KiB |
| Backoffice `/login` móvil | 97 | 100 | 100 | 100 | 0,8 s | 2,7 s | 40 ms | 0 | 25 | 267 KiB |
| Backoffice `/login` escritorio | 100 | 100 | 100 | 100 | 0,2 s | 0,6 s | 0 ms | 0 | 25 | 267 KiB |
| Backoffice `/` móvil | 95 | 100 | 100 | 100 | 0,8 s | 2,9 s | 40 ms | 0 | 38 | 299 KiB |
| Backoffice `/` escritorio | 100 | 100 | 100 | 100 | 0,2 s | 0,7 s | 0 ms | 0 | 38 | 299 KiB |

**Lectura rápida** (umbrales de las skills: LCP bueno ≤ 2,5 s, FCP ≤ 1,8 s, TBT ≤ 200 ms, CLS ≤ 0,1):

- En **escritorio** todo está entre 99 y 100: según la skill `web-perf` (*prioritize ruthlessly*) no
  hay nada que arreglar ahí; los cambios se juzgan sobre todo en móvil.
- En **móvil** falla el **LCP** en las tres páginas principales (3,9 s, 2,9 s y 2,7 s, todas por
  encima de 2,5 s) y el **FCP** de la web (2,1–2,2 s, por encima de 1,8 s).
- **Accesibilidad** baja en la web (92 y 89); el backoffice ya está en 100.
- **CLS** es 0 en todas las páginas y **TBT** está muy por debajo de 200 ms: estabilidad visual e
  interactividad no son un problema.
- **Best Practices** y **SEO** están a 100 en todo (una de las tres ejecuciones de la web dio 96 en
  Best Practices; las otras dos y las capturas, 100).

## 3. Problemas identificados y causa raíz

Ordenados por impacto. "Ahorro estimado" es el que calcula Lighthouse en la medición de móvil.

### 3.1 Sitio corporativo

#### W1 · Tailwind cargado desde el CDN *Play* (`cdn.tailwindcss.com`) — impacto ALTO

- **Síntomas en Lighthouse:** *Render-blocking requests* (ahorro estimado 1.300 ms en `/` y 1.500 ms en
  `/application` en móvil, 360 ms en escritorio), *Reduce unused JavaScript* (38–41 KiB), *Network
  dependency tree*, *Avoid long main-thread tasks* (3–4 tareas largas) y FCP de 2,1–2,2 s.
- **Evidencia:** el HTML pide `https://cdn.tailwindcss.com`, que redirige a `/3.4.17` y descarga un
  **script de 124 KiB comprimido (398 KiB sin comprimir)** en el `<head>`, sin `defer`. Ese script es un
  compilador de Tailwind que **genera el CSS en el navegador** después de leer todo el HTML: hasta que
  termina no hay estilos, y luego fuerza un recálculo de estilos y layout (552 ms de *Style & Layout*
  en el hilo principal).
- **Causa raíz:** se usa una herramienta de prototipado en producción. La propia documentación de
  Tailwind indica que el CDN *Play* es solo para desarrollo. Además, la configuración (`tailwind.config`
  con una paleta `brand` que ninguna clase usa) estaba copiada dentro de `index.html`.

#### W2 · Imagen del carrusel (elemento LCP) sobredimensionada y en otro dominio — impacto ALTO

- **Síntomas:** *Improve image delivery* (ahorro estimado 239–305 KiB; **1.150 ms de LCP en móvil**),
  LCP de 3,9 s en móvil.
- **Evidencia:** el elemento LCP es `<img id="heroImage">`. Se descarga una foto de Unsplash de
  **1.400 px de ancho (342 KiB)** para un hueco de ~380 px CSS en un móvil (~670 px físicos) y de 640 px
  en escritorio. No hay `srcset`/`sizes`, así que todos los dispositivos bajan la versión grande.
- **Causa raíz:** la URL de la imagen es fija (`w=1400`), sin variantes por tamaño de pantalla. Al estar
  en `images.unsplash.com` también exige abrir otra conexión (DNS + TLS) en la ruta crítica. Además
  lleva `decoding="async"`, que la skill `performance` desaconseja para la imagen LCP.

#### W3 · Contraste insuficiente en el botón principal — Accesibilidad

- **Síntoma:** *Background and foreground colors do not have a sufficient contrast ratio*.
- **Evidencia:** "Enviar ahora" (y "Iniciar sesión" en escritorio) usan texto blanco sobre `bg-cyan-600`
  (`#0891b2`): **contraste 3,68:1**, por debajo del 4,5:1 que exige WCAG AA para texto de 16 px.
- **Causa raíz:** elección de tono de color sin comprobar contraste.

#### W4 · Puntos del carrusel demasiado pequeños para tocarlos — Accesibilidad

- **Síntoma:** *Touch targets do not have sufficient size or spacing*.
- **Evidencia:** los tres botones de `#slideDots` miden **12 × 12 px**; el mínimo es 24 × 24 px.
- **Causa raíz:** el botón entero es el punto visual (`h-3 w-3`), sin zona pulsable alrededor.

#### W5 · ARIA mal usado en `/application` — Accesibilidad (89)

- **Síntomas:** *`[aria-*]` attributes do not match their roles* y *Elements with an ARIA `[role]` that
  require children to contain a specific `[role]` are missing some or all of those required children*.
- **Evidencia:** los botones "Enviar"/"Rastrear" tienen `aria-selected` y están dentro de un
  `role="tablist"`, pero **no tienen `role="tab"`**; y 8 `<input>` llevan `aria-expanded`, un atributo
  que no admite un campo de texto.
- **Causa raíz:** `aria-expanded` se usaba como "marca" interna para saber si se había mostrado la ayuda
  del campo (no hay nada que se expanda), y a las subpestañas se les olvidó el rol.

### 3.2 Backoffice

#### B1 · `/login`: el formulario no viene en el HTML — LCP 2,7 s en móvil

- **Síntomas:** LCP 2,7 s con FCP 0,8 s: casi 2 s entre que se pinta algo y se pinta el contenido.
- **Evidencia:** el elemento LCP es el `<h1>Iniciar sesión</h1>`. La página entera estaba dentro de
  `<Suspense fallback={null}>` porque usa `useSearchParams()` para leer `?reset=1`. En una página
  prerenderizada, Next.js pinta el *fallback* de ese Suspense en el HTML estático: **el HTML llegaba
  sin título ni formulario** (solo la cabecera), y el contenido aparecía cuando se descargaba y
  ejecutaba el JavaScript (~250 KiB en 25 peticiones).
- **Causa raíz:** el límite de Suspense envolvía todo el formulario cuando solo el aviso "Contraseña
  actualizada" depende de la URL. Es el patrón *client-side rendering delay* de la skill
  `core-web-vitals` (contenido LCP que depende de JavaScript).

#### B2 · Analizador (`/`): el contenido espera a la API — LCP 2,9 s en móvil

- **Síntomas:** LCP 2,9 s con FCP 0,8 s; el FCP es el texto "Comprobando sesión...".
- **Evidencia:** el elemento LCP es `<h1 id="page-title">`. `AuthGuard` no pinta nada de la vista hasta
  que se cumplen tres pasos en serie: descargar y ejecutar el JS, leer el token de `localStorage` y
  **esperar a `GET /auth/me`** (con su petición *preflight* de CORS: dos viajes de red). En la red móvil
  simulada (RTT 150 ms) cada viaje cuesta; con el backend real, que consulta una base de datos remota
  (Supabase), todavía más.
- **Causa raíz:** el guard valida la sesión contra la API en cada carga, también para un usuario al que
  ya se validó con ese mismo token, y bloquea el render hasta tener la respuesta.

#### B3 · Se precarga una fuente que nadie usa — impacto bajo

- **Evidencia:** cada página precarga **dos** ficheros `woff2` (23 KiB y 29 KiB) en la ruta crítica:
  Geist Sans y Geist Mono. `globals.css` solo usa `--font-geist-sans`; las clases `font-mono` de
  inventario usan la pila monoespaciada del sistema (Tailwind 4), no `--font-geist-mono`.
- **Causa raíz:** restos de la plantilla de `create-next-app`.

#### B4 · CSS que bloquea el render — impacto bajo

- **Síntoma:** *Render-blocking requests* con un CSS de 9 KiB (ahorro estimado 140–150 ms en móvil, 0 ms
  en escritorio).
- **Causa raíz:** Next.js sirve el CSS de Tailwind como `<link rel="stylesheet">` (comportamiento por
  defecto). Next 16 ofrece `experimental.inlineCss` para incrustarlo; se evalúa con medición en
  [REPORT.md](REPORT.md).

#### B5 · *Legacy JavaScript* (13–14 KiB) y *unused JavaScript* (26 KiB) — no accionable

- **Evidencia:** ambos avisos apuntan al mismo *chunk* del framework (70 KiB), que incluye polyfills de
  `Array.prototype.at`, `flat`, `flatMap`, `Object.fromEntries`, `Object.hasOwn` y `trimStart/End`.
- **Causa raíz:** es código del propio Next.js/React, no de la aplicación. El proyecto ya usa los
  navegadores objetivo por defecto de Next 16 (Chrome/Edge/Firefox 111+, Safari 16.4+) y no hay
  ninguna configuración propia que los añada. **No se actúa**: la skill `web-perf` pide verificar antes
  de recomendar y no priorizar cambios sin impacto real; el ahorro estimado en LCP es de 0 ms en el
  analizador.

#### B6 · *Network dependency tree* — informativo

Cadena documento → CSS/fuentes → JS. En el backoffice es la carga normal de una app Next.js; en la web
desaparece al quitar el CDN (W1).

## 4. Código duplicado (componentes y lógica)

| # | Dónde | Qué se repite | Propuesta |
|---|---|---|---|
| D1 | Backoffice: `products-client.tsx`, `orders-client.tsx`, `inbound-client.tsx`, `outbound-client.tsx` | El mismo bloque de carga de datos (~25 líneas): estados `loading`/`loaded`, `useEffect` con bandera `cancelled`, ignorar `SessionExpiredError`, `finally` y un contador `refreshTick` para recargar | **Custom Hook `useApiResource`** |
| D2 | Backoffice: `inbound-client.tsx` y `outbound-client.tsx` | `formRef` + `setFocusField()` idénticos para llevar el foco al primer campo con error | **Custom Hook `useFocusField`** |
| D3 | Web: `index.html` y `application.html` | `markInvalid`, `clearInvalid` y la expresión regular del email copiadas en las dos páginas | **Módulo compartido `js/form-validation.js`** |
| D4 | Web: `index.html` y `application.html` | La carga de Tailwind (CDN) y su configuración | **Una hoja `css/styles.css` compilada** (resuelve también W1) |
| D5 | Web: `application.html` | Las cadenas de clases de pestaña activa/inactiva repetidas 4 veces en `activateMainTab`/`activateSubTab` | **Función `setTabState`** con los estilos en una constante |

También se revisaron `suppliers-client.tsx`, `incidents-manager-client.tsx`, `home-client.tsx` (Talent) y
`record-detail-client.tsx`: tienen cargas parecidas pero con formas de estado distintas (paginación,
peticiones encadenadas, ids de petición para descartar respuestas antiguas). Se dejan fuera para no
mezclar una refactorización amplia con la auditoría; `useApiResource` está pensado para poder
adoptarse ahí más adelante.

## 5. Prioridades

| Prioridad | Problema | Motivo |
|---|---|---|
| 1 | W1 CDN de Tailwind | El mayor ahorro (≈1,3–1,5 s de FCP/LCP en móvil) y afecta a las dos páginas de la web |
| 2 | W2 Imagen LCP | ≈1,15 s de LCP en móvil y ~240–300 KiB menos por visita |
| 3 | B1 Login sin HTML | LCP en "necesita mejorar"; la causa es un límite de Suspense mal colocado |
| 4 | B2 Analizador espera a la API | LCP en "necesita mejorar"; peor aún con el backend real |
| 5 | W3–W5 Accesibilidad | Errores reales para usuarios (contraste, toque, lectores de pantalla) |
| 6 | D1–D5 Duplicación | Mantenibilidad (lo pide la auditoría) |
| 7 | B3 Fuente sin usar, B4 CSS bloqueante | Ahorros pequeños pero de bajo riesgo |
| — | B5 *Legacy/unused JS* del framework | Sin acción: código de Next.js, impacto 0 ms en LCP |
