# REPORT.md — Mejoras aplicadas e impacto medido

Continuación de [AUDIT.md](AUDIT.md): qué se cambió para cada problema, por qué, y cuánto mejoró
**medido en las mismas condiciones que la auditoría inicial**. La explicación didáctica está en
[hito_11.md](hito_11.md).

## 1. Resultado global

### 1.1 Antes y después (Lighthouse CLI, mediana de 3 ejecuciones, mismas condiciones)

Fuente: [docs/lighthouse/before/summary.json](docs/lighthouse/before/summary.json) y
[docs/lighthouse/after/summary.json](docs/lighthouse/after/summary.json), generados con
`node tests/perf/lighthouse.mjs before|after`.

| Caso | Performance | Accessibility | Best Practices | SEO | FCP | LCP | TBT | CLS | Transferido |
|---|---|---|---|---|---|---|---|---|---|
| Web `/` móvil | 86 → **100** | 92 → **100** | 100 | 100 | 2,1 → **0,8 s** | 3,9 → **1,5 s** | 0 ms | 0 | 472 → **112 KiB** |
| Web `/` escritorio | 99 → **100** | 92 → **100** | 100 | 100 | 0,5 → 0,2 s | 0,8 → 0,4 s | 0 ms | 0 | 473 → 112 KiB |
| Web `/application` móvil | 97 → **100** | 89 → **100** | 100 | 100 | 2,1 → **0,9 s** | 2,1 → **0,9 s** | 0 ms | 0 | 129 → **11 KiB** |
| Web `/application` escritorio | 100 | 89 → **100** | 100 | 100 | 0,5 → 0,2 s | 0,5 → 0,2 s | 0 ms | 0 | 129 → 11 KiB |
| Backoffice `/login` móvil | 97 → **98** | 100 | 100 | 100 | 0,8 s | 2,7 → **2,4 s** | 40 → 70 ms | 0 | 267 → 245 KiB |
| Backoffice `/login` escritorio | 100 | 100 | 100 | 100 | 0,2 s | 0,6 → 0,5 s | 0 ms | 0 | 267 → 245 KiB |
| Backoffice `/` móvil | 95 → **96** | 100 | 100 | 100 | 0,8 s | 2,9 → **2,7 s** | 40 → 80 ms | 0 | 299 → 276 KiB |
| Backoffice `/` escritorio | 100 | 100 | 100 | 100 | 0,2 s | 0,7 → 0,6 s | 0 ms | 0 | 299 → 276 KiB |

### 1.2 Sobre las puntuaciones originales (capturas de DevTools)

| Página (móvil) | Captura inicial | Después (CLI) | Métrica clave |
|---|---|---|---|
| Web `/` | 85 / 92 / 100 / 100 | **100 / 100 / 100 / 100** | LCP 3,9 s → **1,5 s** (de "necesita mejorar" a "bueno") |
| Backoffice `/` (analizador) | 95 / 100 / 100 / 100 | 96 / 100 / 100 / 100 | LCP 2,9 s → 2,7 s |
| Backoffice `/login` | 96 / 100 / 100 / 100 | **98** / 100 / 100 / 100 | LCP 2,7 s → **2,4 s** (pasa a "bueno", ≤ 2,5 s) |

En escritorio todas las páginas estaban ya en 99–100 y siguen en 100. Las capturas de DevTools
"después" van en [docs/lighthouse/capturas/despues](docs/lighthouse/capturas/despues) (protocolo en
la [sección 6](#6-capturas-después)).

**Variabilidad:** la web da el mismo resultado en las 3 ejecuciones. En el backoffice móvil hay algo de
ruido: login 96–98 (LCP 2,28–2,73 s) y analizador 96–96 (LCP 2,71 s) después, frente a 97–97 y 91–95
antes. El TBT del backoffice móvil sube de 40 a 70–80 ms: está muy lejos del umbral (200 ms), no
afecta a la nota y no hay ningún cambio de JavaScript en la ruta de carga que lo explique; se
considera ruido de medición.

## 2. Mejoras en el sitio corporativo

### W1 · Tailwind compilado en build en vez del CDN *Play*

**Qué se cambió**

- `uis/website/package.json`: `tailwindcss@3.4.19` (misma versión mayor que el CDN, que servía la
  3.4.17, para que las clases se vean igual) y `serve@14.2.4`, con tres scripts:
  - `npm run build` → compila y minifica `src/styles.css` en `trackflow-web/css/styles.css`
    (15 KiB; **4 KiB** comprimido).
  - `npm run start` → servidor estático de producción en el puerto 3000.
  - `npm run watch` → recompila al editar clases.
- `uis/website/tailwind.config.js`: escanea `trackflow-web/**/*.{html,js}`, así que también entran las
  clases que se ponen desde JavaScript (errores, pestañas, carrusel). La paleta `brand` no se usaba en
  ninguna clase y no se trasladó.
- `index.html` y `application.html`: el `<script src="https://cdn.tailwindcss.com">` (y la
  configuración incrustada) se sustituye por `<link rel="stylesheet" href="css/styles.css">`.
- Contenedor de desarrollo (`uis/start.sh` + `uis/Dockerfile`): Tailwind corre en modo `--watch`
  junto a browser-sync, así que la recarga en caliente sigue funcionando al tocar clases.

**Por qué** (skill `performance` → *Critical rendering path*; `web-perf` → *render-blocking resources*):
el CDN era un script de 124 KiB en el `<head>` que bloqueaba el pintado y además generaba el CSS en el
navegador. Un CSS precompilado de 4 KiB elimina el script, la redirección y el trabajo de *Style &
Layout* en el hilo principal.

**Impacto medido:** FCP móvil 2,1 → 0,8 s (`/`) y 2,1 → 0,9 s (`/application`); desaparecen *Reduce
unused JavaScript* (38–41 KiB) y las tareas largas; `/application` pasa de 129 a 11 KiB transferidos.

### W2 · Imagen LCP responsive, en WebP y servida desde el propio sitio

**Qué se cambió**

- Las tres fotos del carrusel se descargaron una vez y se convirtieron a **WebP** (calidad 72) en
  **480, 800 y 1.200 px**: `trackflow-web/img/hero-{1,2,3}-{480,800,1200}.webp`. La primera pesa
  43 / 101 / 185 KiB según el ancho (antes: 342 KiB siempre).
- `<img id="heroImage">` usa `srcset` + `sizes="(min-width: 1280px) 640px, (min-width: 768px) 50vw, 100vw"`:
  el navegador elige el ancho que necesita su pantalla.
- Se quitó `decoding="async"` (la skill lo desaconseja en la imagen LCP) y se mantiene
  `fetchpriority="high"`. No se añadió `preload`: la imagen ya está en el HTML inicial y la skill pide
  precargar solo si la traza muestra descubrimiento tardío.
- El carrusel actualiza `srcset` y `src` al cambiar de slide.
- Se probó también AVIF: con esta foto (muy detallada) pesaba lo mismo o más que WebP, así que se
  descartó para no complicar el marcado con `<picture>`.

**Por qué** (skill `core-web-vitals` → *LCP: slow resource load times*; `performance` → *Responsive
images*): la imagen es el elemento LCP de la portada; cada KiB de más retrasa directamente el LCP.
Servirla desde el mismo origen evita además abrir una conexión a otro dominio.

**Impacto medido:** LCP móvil **3,9 → 1,5 s**; escritorio 0,8 → 0,4 s; la portada pasa de 472 a
112 KiB. *Improve image delivery* baja de 239–305 KiB a ~52 KiB de ahorro estimado (ver
[sección 5](#5-lo-que-queda-y-por-qué-no-se-ha-tocado)).

### W3 · Contraste del botón principal

`bg-cyan-600` → `bg-cyan-700` (y `hover:bg-cyan-700` → `hover:bg-cyan-800`) en "Enviar ahora" y en
"Iniciar sesión" de escritorio. Contraste con texto blanco: **3,68:1 → 5,36:1** (WCAG AA pide 4,5:1).
Es el mismo tono que ya usaban los botones de enviar formulario de la web.

### W4 · Zona táctil de los puntos del carrusel

Cada punto es ahora un botón de **24 × 24 px** (`flex h-6 w-6`) con el punto visual de 12 px dentro.
Se ve igual y cumple el mínimo de tamaño de objetivo táctil.

### W5 · ARIA correcto en `/application`

- `role="tab"` en "Enviar" y "Rastrear" (ya estaban dentro de un `role="tablist"` y usaban
  `aria-selected`).
- Se quitaron los 11 `aria-expanded` de `<input>`/`<select>` y el JavaScript que los cambiaba: no había
  nada que se expandiera; se usaban como marca interna para la ayuda del campo. La ayuda se sigue
  mostrando igual (depende de `data-hint-for`).

**Impacto medido (W3–W5):** Accessibility **92 → 100** en `/` y **89 → 100** en `/application`.

## 3. Mejoras en el backoffice

### B1 · `/login`: el formulario sale en el HTML prerenderizado

**Qué se cambió:** en `app/(auth)/login/page.tsx`, el `<Suspense fallback={null}>` envolvía toda la
página porque usaba `useSearchParams()` para el aviso de `?reset=1`. Ahora solo ese aviso
(`PasswordResetNotice`) está dentro del Suspense; el título y el formulario forman parte del HTML
estático.

**Por qué** (skill `core-web-vitals` → *LCP: client-side rendering delays*): el elemento LCP no debe
depender de que llegue y se ejecute el JavaScript.

**Impacto medido:**

- En la traza real (sin simulación), el `<h1>` se pinta **en el primer pintado**: LCP observado =
  FCP observado (117 ms). Antes, el LCP llegaba 42 ms después del primer pintado.
- Peticiones antes del LCP: **19 → 13** (243 → 191 KiB).
- LCP simulado (móvil): **2,7 → 2,4 s**, ya dentro de "bueno" (≤ 2,5 s); Performance 97 → 98.
- Se comprobó en el navegador que `/login?reset=1` sigue mostrando "Contraseña actualizada".

> **Por qué no baja más.** Lighthouse no mide el móvil lento de verdad: **simula** la carga (modelo
> *Lantern*) a partir de la traza real. En ese modelo, todo lo que se pidió antes del LCP observado
> cuenta para el LCP, y Next.js pide sus *chunks* de JavaScript desde el `<head>` (son asíncronos y no
> bloquean el pintado, pero empiezan antes). El LCP simulado restante es, sobre todo, la descarga del
> JavaScript del framework (ver B5).

### B3 · Una sola fuente precargada

`app/layout.tsx` ya no carga `Geist_Mono`: su variable no la usaba ningún estilo, pero su `woff2` se
precargaba en todas las páginas. **Impacto:** −1 petición y −23 KiB en la ruta crítica de todas las
páginas del backoffice.

**Impacto medido en el analizador** (la única mejora que le afecta): peticiones antes del LCP 250 →
227 KiB; LCP observado 183 → 152 ms; LCP simulado móvil **2,9 → 2,7 s** (en las 3 ejecuciones);
Performance 95 → 96 (rango 91–95 → 96–96).

### Probado y descartado (con medición)

| Idea | Resultado | Decisión |
|---|---|---|
| **B2 · Caché del usuario de la sesión** (`AuthGuard` pinta la vista con el último `GET /auth/me` del mismo token y revalida en segundo plano) | Analizador móvil: 95 y LCP 2,9 s, **igual que antes**. En local `/auth/me` tarda ~5 ms y el LCP lo limita la hidratación del JavaScript; Lighthouse además sustituye la latencia real por la simulada | **Revertido.** Cambiaba la semántica de la autenticación (pinta antes de validar) y guardaba datos del usuario en `localStorage` sin ninguna mejora medible. La skill `web-perf`: *don't prioritize changes with 0 ms impact* |
| **B4 · `experimental.inlineCss`** (CSS incrustado en el HTML en vez de `<link>`) | Login 97 / LCP 2,5 s, analizador 95 / LCP 2,9 s: **sin mejora** (FCP igual, 0,8 s) | **Revertido.** Es experimental, impide cachear el CSS entre páginas y no aporta nada medible |

Los resúmenes del experimento con `inlineCss` están en
[docs/lighthouse/exp-inlinecss/summary.json](docs/lighthouse/exp-inlinecss/summary.json).

## 4. Código duplicado: refactorizaciones

| # | Antes | Después | Archivos |
|---|---|---|---|
| D1 | El mismo `useEffect` de carga (~25 líneas: `loading`, `loaded`, bandera `cancelled`, `SessionExpiredError`, `refreshTick`) repetido en 4 pantallas de inventario | **Custom Hook `useApiResource(fetcher, initial, { key, onLoaded, onError })`** que devuelve `{ data, setData, loaded, loading, reload }` | nuevo `app/lib/use-api-resource.ts`; `products-client.tsx`, `orders-client.tsx`, `inbound-client.tsx`, `outbound-client.tsx` |
| D2 | `formRef` + `setFocusField()` idénticos en entrada y salida de stock | **Custom Hook `useFocusField()`** → `{ formRef, focusField }` | `app/ui/inventory-ui.tsx`; `inbound-client.tsx`, `outbound-client.tsx` |
| D3 | `markInvalid`, `clearInvalid` y la regex del email copiados en las dos páginas de la web | **Módulo compartido `js/form-validation.js`** (`window.TrackflowForms`) | nuevo `trackflow-web/js/form-validation.js`; `index.html`, `application.html` |
| D4 | Carga y configuración de Tailwind en cada página | **Una hoja compilada** compartida (`css/styles.css`), cacheable entre páginas | ver W1 |
| D5 | Cadenas de clases de pestaña activa/inactiva repetidas 4 veces | **`setTabState(tab, isActive, styles)`** + constantes `MAIN_TAB_STYLES` / `SUB_TAB_STYLES` | `application.html` |

Balance: en las cuatro pantallas de inventario y `inventory-ui.tsx` se eliminan 134 líneas y se
añaden 61; el hook nuevo suma 70 (con sus tipos y comentarios). La ganancia no está en el número de líneas,
sino en que la lógica delicada (descartar respuestas tardías, ignorar la sesión caducada, recargar)
vive en un solo sitio: un arreglo futuro se hace una vez y vale para todas las pantallas. El
comportamiento no cambia: lo cubren las 40 comprobaciones de la suite de UI de inventario (carga,
filtros, "Actualizar", preselección por `?sku_id=`, errores), que pasan todas.

## 5. Lo que queda y por qué no se ha tocado

| Aviso de Lighthouse | Dónde | Motivo |
|---|---|---|
| *Legacy JavaScript* (14 KiB) y *Reduce unused JavaScript* (26 KiB) | Backoffice | Están en un *chunk* del propio Next.js (polyfills y código del framework). El proyecto ya usa los navegadores objetivo por defecto; no es código de la app. Ahorro en LCP del analizador: 0 ms |
| *Render-blocking requests* (≈150 ms est. en móvil) | Web y backoffice | Es un CSS de 4 KiB (web) o 9 KiB (backoffice). En el backoffice se probó incrustarlo (`inlineCss`) sin mejora. En la web haría falta duplicar el CSS dentro de cada HTML con otro paso de build; el FCP ya es 0,8–0,9 s (umbral 1,8 s) |
| *Use efficient cache lifetimes* (106 KiB) | Web | `serve` no envía cabeceras de caché largas. Es configuración del servidor o CDN de producción, no del código; como los ficheros no llevan *hash* en el nombre, la skill recomienda `max-age=86400, stale-while-revalidate=604800`, no caché inmutable. Recomendación para el despliegue |
| *Improve image delivery* (~52 KiB) | Web | Con `object-cover` el hueco de la imagen no tiene la proporción de la foto, así que ningún ancho encaja exacto. LCP ya en 1,5 s (móvil) |
| LCP del analizador en 2,7 s | Backoffice | El token está en `localStorage`, que el servidor no puede leer: la vista con sesión solo puede pintarse después de hidratar. Bajarlo de verdad exigiría sesión en *cookie* y comprobarla en el servidor (cambio de arquitectura de la autenticación, fuera del alcance de esta auditoría) |

## 6. Capturas "después"

Las capturas de DevTools posteriores a los cambios se toman igual que las iniciales (incógnito,
DevTools → Lighthouse → *Navigation*, móvil y escritorio):

```sh
docker compose up -d backend                                   # API en :8000
cd uis/backoffice && npm run build && npm run start            # :3001
cd uis/website   && npm ci && npm run build && npm run start   # :3000 (ahora con build y start)
```

y se guardan en [docs/lighthouse/capturas/despues](docs/lighthouse/capturas/despues) con los mismos
nombres que las de [antes](docs/lighthouse/capturas/antes).

## 7. Verificación

| Comprobación | Resultado |
|---|---|
| Suites de UI (`node tests/ui/run.mjs`): web, backoffice, incidencias, proveedores, inventario, talent | **181 / 181** |
| Tests unitarios del backoffice (`npx jest`) | **148 / 148** |
| TypeScript (`npx tsc --noEmit`) | Sin errores |
| ESLint | Sin errores nuevos (los 2 que hay son previos, en `record-detail-client.tsx`, que no se ha tocado) |
| `/login?reset=1` en navegador | Muestra "Contraseña actualizada" |

Los tests de la web se actualizaron porque comprobaban la implementación anterior: que existiera el
runtime del CDN (`window.tailwind`) y que las imágenes vinieran de `images.unsplash.com`. Ahora
comprueban que la hoja compilada está cargada y que las imágenes son locales, y la web ya no hace
**ninguna** petición externa.
