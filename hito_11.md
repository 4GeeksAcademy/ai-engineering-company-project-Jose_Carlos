# Hito 11 — Auditoría de rendimiento de los dos frontends

Este documento explica, desde cero, **qué es auditar el rendimiento de una web**, cómo se ha
auditado TrackFlow, qué problemas aparecieron, qué se ha cambiado y **por qué** cada cambio importa.
Está pensado para que alguien que no ha visto nunca Lighthouse termine de leerlo sabiendo hacer una
auditoría por su cuenta y entendiendo cada decisión.

Los entregables formales son tres:

- [AUDIT.md](AUDIT.md): puntuaciones iniciales, problemas y causa raíz de cada uno.
- [REPORT.md](REPORT.md): mejoras aplicadas e impacto medido sobre las puntuaciones originales.
- Las capturas de Lighthouse antes y después: [docs/lighthouse/capturas](docs/lighthouse/capturas).

Este hito es la versión "para estudiar" de todo eso.

---

## Índice

1. [El encargo](#1-el-encargo)
2. [Conceptos básicos](#2-conceptos-básicos)
3. [Las dos aplicaciones que se auditan](#3-las-dos-aplicaciones-que-se-auditan)
4. [Por qué se audita con `build` + `start` y no con `dev`](#4-por-qué-se-audita-con-build--start-y-no-con-dev)
5. [Las skills de agente y para qué sirven](#5-las-skills-de-agente-y-para-qué-sirven)
6. [Cómo se midió: capturas y script reproducible](#6-cómo-se-midió-capturas-y-script-reproducible)
7. [Qué encontró la auditoría](#7-qué-encontró-la-auditoría)
8. [Los cambios, uno a uno, y por qué importan](#8-los-cambios-uno-a-uno-y-por-qué-importan)
9. [Código duplicado: componentes compartidos y Custom Hooks](#9-código-duplicado-componentes-compartidos-y-custom-hooks)
10. [Resultados](#10-resultados)
11. [Lo que no se cambió (y por qué)](#11-lo-que-no-se-cambió-y-por-qué)
12. [Cómo se comprobó que nada se ha roto](#12-cómo-se-comprobó-que-nada-se-ha-roto)
13. [Cómo repetir la auditoría tú solo](#13-cómo-repetir-la-auditoría-tú-solo)
14. [Archivos creados y modificados](#14-archivos-creados-y-modificados)
15. [Glosario](#15-glosario)

---

## 1. El encargo

El correo pedía, para el **sitio corporativo** y el **backoffice**:

1. Pasar **Lighthouse** y registrar las puntuaciones iniciales de Performance, Accessibility, Best
   Practices y SEO.
2. Revisar el código y encontrar **componentes o lógica duplicados** que puedan convertirse en un
   componente compartido o en un **Custom Hook**.
3. Usar unas *skills* de agente (`core-web-vitals`, `performance`, `web-perf`) para guiar las
   correcciones y **aplicar las que identifiquen como necesarias**.
4. Entregar `AUDIT.md`, `REPORT.md` y capturas de antes y después.

---

## 2. Conceptos básicos

### ¿Qué es "auditar" una web?

Auditar es **medir** cómo se comporta la web, **compararlo con unos umbrales** aceptados por la
industria, **encontrar la causa** de lo que no llega al umbral y **proponer (y aplicar) arreglos**,
volviendo a medir después para comprobar que han funcionado. La palabra clave es *medir*: una
auditoría seria no se basa en impresiones ("parece lenta"), sino en números tomados siempre en las
mismas condiciones.

El ciclo es siempre el mismo:

```
medir  →  diagnosticar la causa raíz  →  corregir  →  volver a medir en las mismas condiciones
```

### ¿Qué es Lighthouse?

Lighthouse es una herramienta de Google (viene dentro de Chrome, en las DevTools, y también como
programa de línea de comandos) que carga una página, la observa y la puntúa de 0 a 100 en cuatro
categorías:

| Categoría | Qué mide | Ejemplos de lo que penaliza |
|---|---|---|
| **Performance** | Lo rápido que se ve y responde la página | Scripts que bloquean el pintado, imágenes enormes |
| **Accessibility** | Si la puede usar todo el mundo (lector de pantalla, teclado, baja visión) | Poco contraste, botones diminutos, ARIA mal puesto |
| **Best Practices** | Buenas prácticas técnicas | Errores en consola, librerías con vulnerabilidades |
| **SEO** | Si los buscadores la entienden | Falta de `<title>`, de `meta description`, enlaces sin texto |

Colores: **verde** 90–100 (bien), **naranja** 50–89 (mejorable), **rojo** 0–49 (mal).

> En las capturas aparece una quinta burbuja, **Agentic Browsing** ("2/2"). Es una categoría nueva
> de Lighthouse que comprueba si un agente de IA puede navegar la página. No forma parte del
> encargo; estaba en verde en todas las páginas.

### Las métricas de Performance

La nota de Performance no es una opinión: es una **media ponderada de cinco métricas**. Conviene
saber qué es cada una, porque cada problema empeora una métrica concreta:

| Métrica | Qué significa | Bueno |
|---|---|---|
| **FCP** — *First Contentful Paint* | Cuándo aparece **lo primero** (un texto, un logo) | ≤ 1,8 s |
| **LCP** — *Largest Contentful Paint* | Cuándo aparece **lo más grande** de la pantalla (normalmente la imagen o el título principal). Es "cuándo siente el usuario que la página ha cargado" | ≤ 2,5 s |
| **TBT** — *Total Blocking Time* | Cuánto tiempo el navegador está "atascado" ejecutando JavaScript y no puede responder a clics | ≤ 200 ms |
| **CLS** — *Cumulative Layout Shift* | Cuánto "salta" el contenido mientras carga (el típico botón que se mueve justo cuando vas a pulsarlo) | ≤ 0,1 |
| **SI** — *Speed Index* | Lo rápido que se va llenando la pantalla visualmente | ≤ 3,4 s |

**LCP**, **CLS** e **INP** (este último mide la respuesta a interacciones reales y no se puede medir
en una carga de laboratorio; TBT es su aproximación) son las **Core Web Vitals**: las tres métricas
que Google usa para valorar la experiencia de una página.

### Laboratorio frente a datos reales

Lighthouse es una medición de **laboratorio**: una sola carga, en un ordenador concreto, con la red y
la CPU **ralentizadas a propósito** para imitar un móvil de gama media con 4G lento (en móvil:
150 ms de latencia, 1,6 Mbps y la CPU 4 veces más lenta). Por eso la misma página saca 100 en
escritorio y 85 en móvil: **el móvil es la prueba exigente**.

Los datos **reales** (de usuarios de verdad) se recogen de otra forma (CrUX, RUM) y necesitan tráfico
en producción. TrackFlow corre en local, así que no hay datos reales: todo lo de este hito es
laboratorio, y así se indica en los informes.

### ¿Qué es la "ruta crítica"?

Para pintar una página, el navegador descarga el HTML y, mientras lo lee, descubre otros ficheros
(CSS, JavaScript, fuentes, imágenes). Algunos **bloquean el pintado**: el navegador no pinta nada
hasta tenerlos (por ejemplo, el CSS, o un `<script>` normal en el `<head>`). La cadena de ficheros que
hay que descargar sí o sí antes de ver la página es la **ruta crítica**. Casi todas las mejoras de
rendimiento consisten en **acortarla**: menos ficheros, más pequeños, descubiertos antes, o fuera
de ella.

---

## 3. Las dos aplicaciones que se auditan

| | Sitio corporativo | Backoffice |
|---|---|---|
| Carpeta | `uis/website/trackflow-web` | `uis/backoffice` |
| Tecnología | HTML + Tailwind + JavaScript sin framework | Next.js 16 + React 19 + Tailwind 4 |
| Páginas auditadas | `/` (landing) y `/application` (formulario de envío) | `/login` y `/` (analizador de incidencias, con sesión) |
| Puerto | 3000 | 3001 |

El backoffice necesita además la **API** (FastAPI, puerto 8000) para validar la sesión.

---

## 4. Por qué se audita con `build` + `start` y no con `dev`

`npm run dev` arranca un **servidor de desarrollo**, pensado para programar cómodo, no para ser
rápido:

| `next dev` | `next build` + `next start` |
|---|---|
| JavaScript y CSS **sin minificar**, con *source maps* | Ficheros minificados y sin código muerto |
| React en **modo desarrollo** (más pesado, con comprobaciones extra y renders dobles) | React en modo producción |
| Cada página se **compila la primera vez que se visita** (el primer TTFB es enorme) | Todo compilado de antemano; 17 de las 19 rutas son HTML estático |
| Inyecta el cliente de **recarga en caliente** (un websocket) y el indicador de Next | No añade nada |

Si se auditara con `dev`, Lighthouse "descubriría" problemas que en producción no existen (JS sin
minificar, tiempos de compilación…). La auditoría tiene que hacerse sobre **lo que recibe el usuario
real**: el *build* de producción.

En la web estática pasa lo mismo: el contenedor de desarrollo la sirve con `browser-sync`, que
inyecta un script de recarga en cada página. Para auditar se sirve con un servidor estático normal
(`serve`), y desde este hito también con `npm run build` + `npm run start` (ver la
[sección 8.1](#81-web-tailwind-compilado-en-vez-del-cdn)).

---

## 5. Las skills de agente y para qué sirven

Una *skill* es un paquete de instrucciones (ficheros Markdown) que un agente de IA carga para hacer
una tarea siguiendo un método concreto. Se instalaron las tres que pedía el correo:

```sh
npx skills add https://github.com/addyosmani/web-quality-skills --skill core-web-vitals
npx skills add https://github.com/addyosmani/web-quality-skills --skill performance
npx skills add https://github.com/cloudflare/skills --skill web-perf
```

Quedan en `.agents/skills/` (y enlazadas desde `.claude/skills/`). Se revisó su contenido antes de
usarlas: son solo guías, no ejecutan nada.

| Skill | Qué aporta | Cómo se usó aquí |
|---|---|---|
| `performance` | Método general: **medir antes de tocar**, comparar en condiciones repetibles (≥ 3 ejecuciones, mediana), presupuestos de peso, imágenes responsive, CSS/JS que bloquean | Diseño del script de medición; corrección de la imagen y del CSS de la web |
| `core-web-vitals` | Diagnóstico por métrica (LCP, INP, CLS) y sus causas típicas | Causa del LCP del login y del analizador ("*client-side rendering delay*"); prioridad de la imagen LCP |
| `web-perf` (Cloudflare) | Flujo de auditoría por fases y reglas de criterio: **verificar antes de recomendar**, **cuantificar**, **no arreglar lo que tiene 0 ms de impacto**, **priorizar sin piedad** | Decidir qué *no* tocar (escritorio a 100, *legacy JS* del framework) y el formato de AUDIT.md |

Las tres coinciden en una idea que guía todo el hito: **no se cambia nada sin una medición que
justifique el cambio, y no se da por bueno ningún cambio sin volver a medir**.

---

## 6. Cómo se midió: capturas y script reproducible

### 6.1 Las capturas (Chrome DevTools)

Son las puntuaciones "oficiales". Pasos que se siguieron:

1. Arrancar el backend (`docker compose up -d backend`), el backoffice (`npm run build` y
   `npm run start`) y la web (servidor estático en el 3000).
2. Abrir Chrome en **incógnito** (las extensiones alteran el resultado).
3. Para el analizador, iniciar sesión primero (es una página con sesión).
4. DevTools (`F12`) → pestaña **Lighthouse** → modo *Navigation* → dispositivo **Mobile** y luego
   **Desktop** → *Analyze page load*.
5. Capturar la puntuación y la lista de *Insights*/*Diagnostics*.

Están en [docs/lighthouse/capturas/antes](docs/lighthouse/capturas/antes) y
[docs/lighthouse/capturas/despues](docs/lighthouse/capturas/despues).

### 6.2 El script reproducible (`tests/perf/lighthouse.mjs`)

Una captura es una sola ejecución, y Performance **varía** entre ejecuciones. Para comparar antes y
después con rigor (lo que pide la skill `performance`) se escribió un script que:

- arranca **todo** por su cuenta en puertos propios (web en 4000, backoffice en 4001 compilado con
  `npm run build`, API en 8100 con una base de datos **desechable**, nunca la de Supabase), para no
  interferir con lo que tengas arrancado a mano;
- lanza **Chrome headless** sin extensiones y le conecta la **CLI de Lighthouse 13.5.0**;
- mide 4 páginas × 2 dispositivos × **3 ejecuciones**, y se queda con la **mediana**;
- vacía la caché HTTP antes de cada ejecución (todas son cargas "en frío");
- para el analizador, abre sesión con una cuenta sintética y simula un **usuario que vuelve** (abre la
  vista una vez y mide la siguiente carga), que es el caso de las capturas;
- guarda un resumen en `docs/lighthouse/<etiqueta>/summary.json` y el informe HTML completo de cada
  caso (este último solo en local: pesa ~0,9 MB y se regenera con el script).

```sh
node tests/perf/lighthouse.mjs before   # antes de los cambios
node tests/perf/lighthouse.mjs after    # después
```

**Comprobación de que el script mide lo mismo que las capturas:** web móvil 86 (captura 85), login
móvil 97 (captura 96), analizador móvil 95 con LCP 2,9 s (captura 95 y 2,9 s). Coinciden.

> **Un fallo del propio script que conviene conocer.** La primera versión vaciaba la caché *antes*
> de abrir `/login` para poner el token… y abrir `/login` volvía a llenar la caché con el JavaScript
> compartido. El analizador salió con 100 y solo 55 KiB transferidos: era una carga "en caliente".
> Se detectó porque no cuadraba con la captura (95), se corrigió el orden y se repitió la medición.
> Lección: **si un número no cuadra con otra fuente, sospecha primero de la medición**.

---

## 7. Qué encontró la auditoría

El detalle completo, con evidencias, está en [AUDIT.md](AUDIT.md). Resumido:

**Puntuaciones iniciales en móvil** (capturas): web 85 / 92 / 100 / 100; analizador 95 / 100 / 100 /
100; login 96 / 100 / 100 / 100. En escritorio, todo entre 99 y 100.

**El síntoma común:** el **LCP en móvil** suspendía en las tres páginas (3,9 s, 2,9 s y 2,7 s; el
umbral es 2,5 s). Y la web tenía problemas de **accesibilidad** (92 y 89).

| Problema | Causa raíz |
|---|---|
| Web: CSS que bloquea el pintado 1,3–1,5 s | Tailwind se cargaba desde su CDN *Play*: un **script de 124 KiB** que genera el CSS **en el navegador**. Es una herramienta de prototipado, no de producción |
| Web: imagen principal pesada (LCP 3,9 s) | Foto de 1.400 px y 342 KiB para un hueco de ~380 px en móvil, sin variantes por tamaño y desde otro dominio |
| Web: contraste insuficiente | Texto blanco sobre `cyan-600`: 3,68:1 (mínimo 4,5:1) |
| Web: botones diminutos | Puntos del carrusel de 12 × 12 px (mínimo 24 × 24) |
| Web: ARIA incorrecto | Pestañas sin `role="tab"` y `aria-expanded` usado como marca interna en campos de texto |
| Login: el contenido llega tarde | Todo el formulario estaba dentro de un `<Suspense fallback={null}>`: el HTML llegaba **vacío** y el formulario esperaba al JavaScript |
| Analizador: el contenido llega tarde | La sesión vive en `localStorage`: el servidor no puede saber si hay sesión y la vista se pinta tras hidratar y llamar a `/auth/me` |
| Backoffice: fuente sin usar | Se precargaba Geist Mono (23 KiB) en todas las páginas sin que ningún estilo la usara |
| Backoffice: *Legacy/Unused JavaScript* | Código del propio Next.js: no es de la app y no se actúa |

---

## 8. Los cambios, uno a uno, y por qué importan

### 8.1 Web: Tailwind compilado en vez del CDN

**El problema explicado.** Imagina que, para leer un libro, primero tuvieras que descargar una
imprenta, montarla y que te imprimiera el libro en casa. Eso hacía el CDN de Tailwind: el navegador
descargaba un programa (124 KiB) que leía todo el HTML, buscaba las clases (`bg-cyan-700`,
`rounded-full`…) y **fabricaba el CSS en ese momento**. Hasta que terminaba, la página no tenía
estilos; después, el navegador tenía que recalcularlo todo.

**La solución.** Fabricar el CSS **una vez, al hacer el build**, y servir el resultado:

```sh
cd uis/website
npm run build    # tailwindcss lee el HTML/JS y escribe trackflow-web/css/styles.css (4 KiB comprimido)
npm run start    # servidor estático de producción en :3000
```

`tailwind.config.js` le dice a Tailwind dónde buscar clases (`trackflow-web/**/*.{html,js}`), así que
también incluye las que se añaden desde JavaScript. Se usa **Tailwind 3**, la misma versión mayor que
servía el CDN, para que todo se vea exactamente igual.

**Detalle importante:** `css/styles.css` es un fichero **generado**. Si cambias clases en el HTML, hay
que volver a ejecutar `npm run build` (o dejar `npm run watch` abierto). En Docker ya se hace solo:
`uis/start.sh` lanza Tailwind en modo *watch* junto a browser-sync.

**Por qué importa:** es el cambio con más impacto de todo el hito. FCP móvil de 2,1 s a 0,8 s, y la
página `/application` pasa de descargar 129 KiB a 11 KiB.

### 8.2 Web: la imagen principal

**El problema explicado.** Un móvil mostraba la foto en un hueco de unos 380 píxeles de ancho, pero
descargaba la versión de 1.400 píxeles (342 KiB). Es como mandar un póster para ponerlo en un sello.

**La solución.** Tres versiones de cada foto (480, 800 y 1.200 px) en **WebP** (un formato más
moderno y ligero que JPEG), y dejar que el navegador elija:

```html
<img id="heroImage"
     src="img/hero-1-800.webp"
     srcset="img/hero-1-480.webp 480w, img/hero-1-800.webp 800w, img/hero-1-1200.webp 1200w"
     sizes="(min-width: 1280px) 640px, (min-width: 768px) 50vw, 100vw"
     width="1200" height="800" fetchpriority="high" alt="…" />
```

- `srcset` = "estas son las versiones disponibles y su ancho".
- `sizes` = "en esta pantalla la imagen ocupará este ancho". Con eso el navegador calcula cuál le
  basta (teniendo en cuenta la densidad de píxeles de la pantalla).
- `fetchpriority="high"` = "esta imagen es la importante: pídela la primera".
- `width`/`height` = el navegador reserva el hueco antes de que llegue la imagen, así nada "salta"
  (CLS 0).

Las fotos se sirven ahora desde el propio sitio (`img/`), así que el navegador no tiene que abrir
otra conexión con un dominio externo. También se probó **AVIF** (aún más moderno), pero con esta foto
no pesaba menos que WebP, así que no compensaba complicar el código.

**Por qué importa:** la imagen **es** el LCP de la portada. LCP móvil de 3,9 s a **1,5 s**.

### 8.3 Web: accesibilidad

La accesibilidad no es un extra: es que la web la pueda usar una persona con baja visión, alguien que
navega con lector de pantalla o alguien con el pulgar grande en un móvil.

| Cambio | Para quién |
|---|---|
| Botón principal de `cyan-600` a `cyan-700` (contraste 3,68:1 → 5,36:1) | Personas con baja visión o con el móvil al sol |
| Puntos del carrusel: zona pulsable de 24 × 24 px con el punto de 12 px dentro | Cualquiera que use pantalla táctil |
| `role="tab"` en las subpestañas y fuera los `aria-expanded` de los campos | Usuarios de lector de pantalla: antes se anunciaban "desplegables" que no lo eran |

Resultado: Accessibility **92 → 100** y **89 → 100**.

### 8.4 Backoffice: el login ya viene en el HTML

**Qué es un "límite de Suspense".** En React, `<Suspense fallback={X}>` significa: "si lo de dentro
todavía no puede pintarse, pinta X mientras tanto". En Next.js, cuando una página se genera como HTML
estático en el build y usa `useSearchParams()` (leer la URL, que en el build no existe), lo que va
dentro del Suspense **no se incluye en el HTML**: se incluye el `fallback`.

**El problema.** El login envolvía **toda** la página en `<Suspense fallback={null}>` solo porque un
aviso pequeño ("Contraseña actualizada", que sale con `?reset=1`) leía la URL. Resultado: el HTML del
login llegaba sin título ni formulario, y aparecían cuando el JavaScript se descargaba y ejecutaba.

**La solución.** Meter en el Suspense **solo** lo que lee la URL:

```tsx
function PasswordResetNotice() {
  if (useSearchParams().get("reset") !== "1") return null;
  return <p role="status">Contraseña actualizada. …</p>;
}

// dentro del formulario, que ya no está envuelto:
{!error && (
  <Suspense fallback={null}>
    <PasswordResetNotice />
  </Suspense>
)}
```

**Por qué importa:** en la traza real, el título se pinta **en el primer pintado** (antes, 42 ms
después), y antes del LCP se descargan 13 ficheros en vez de 19. El LCP simulado de Lighthouse baja
de 2,7 s a **2,4 s**: pasa a "bueno".

> **Lección sobre la simulación.** Lighthouse no carga la página en un móvil lento de verdad: la carga
> rápido y luego **calcula** cuánto habría tardado en un móvil lento (modelo *Lantern*). En ese cálculo,
> todo lo que se pidió antes del LCP real cuenta para el LCP, aunque no lo bloquee. Next.js pide sus
> ficheros de JavaScript desde el principio, así que siguen "pesando" en el LCP simulado. Por eso
> conviene mirar también los tiempos **observados** (están en el informe JSON, en `metrics`).

### 8.5 Backoffice: una fuente menos

`app/layout.tsx` cargaba dos fuentes de Google con `next/font`: Geist (la que usa el texto) y Geist
Mono. Ningún estilo usaba Geist Mono (las tablas de inventario con `font-mono` usan la fuente
monoespaciada del sistema), pero `next/font` la **precargaba** en todas las páginas: 23 KiB en la ruta
crítica para nada. Se quitó.

**Por qué importa:** es la mejora que mueve el analizador: LCP simulado 2,9 → 2,7 s y Performance
95 → 96, estable en las tres ejecuciones.

### 8.6 Lo que se probó y se deshizo

Una parte importante de auditar es **descartar ideas que no funcionan**, con datos:

1. **Caché del usuario de la sesión.** Idea: guardar el resultado de `/auth/me` y, la próxima vez,
   pintar la vista sin esperar a la API. Medido: **ninguna mejora** (en local la API responde en
   ~5 ms; lo que limita es el JavaScript). Además cambiaba cómo funciona la seguridad (pintar antes de
   validar) y guardaba datos personales en `localStorage`. **Se deshizo.**
2. **`experimental.inlineCss` de Next.js.** Idea: meter el CSS dentro del HTML para que no bloquee.
   Medido: **ninguna mejora**, y es una opción experimental que impide cachear el CSS. **Se deshizo.**

Ambos están documentados en [REPORT.md](REPORT.md) con sus números. Es justo lo que pide la skill
`web-perf`: no quedarse cambios con 0 ms de impacto.

---

## 9. Código duplicado: componentes compartidos y Custom Hooks

### ¿Qué es un Custom Hook?

En React, un *hook* es una función que empieza por `use` y que puede usar estado (`useState`) y
efectos (`useEffect`). Un **Custom Hook** es un hook escrito por nosotros para **reutilizar lógica
con estado** entre componentes. Es a la lógica lo que un componente es a la interfaz.

### El duplicado principal: cargar datos de la API

Cuatro pantallas de inventario (stock, movimientos, entrada y salida) repetían casi el mismo bloque:

```tsx
const [skus, setSkus] = useState<Sku[]>([]);
const [loaded, setLoaded] = useState(false);
const [loading, setLoading] = useState(true);
const [refreshTick, setRefreshTick] = useState(0);

useEffect(() => {
  let cancelled = false;                    // por si la pantalla se cierra antes de la respuesta
  inventoryApi.listSkus()
    .then((list) => { if (cancelled) return; setSkus(list); setLoaded(true); })
    .catch((error) => {
      if (cancelled || error instanceof SessionExpiredError) return;   // el guard ya lleva al login
      setAlert({ type: "error", message: `No se pudo cargar el stock. ${errorMessage(error)}` });
      setLoaded(false);
    })
    .finally(() => { if (!cancelled) setLoading(false); });
  return () => { cancelled = true; };
}, [refreshTick]);
```

Ahora todo eso es **`useApiResource`** (`app/lib/use-api-resource.ts`), y cada pantalla queda así:

```tsx
const { data: skus, loaded, loading, reload } = useApiResource(inventoryApi.listSkus, [] as Sku[], {
  onError: (error) => setAlert({ type: "error", message: `No se pudo cargar el stock. ${errorMessage(error)}` }),
});
```

- `key`: si cambia (por ejemplo, el `?sku_id=` de la URL), se vuelve a pedir.
- `onLoaded`: para lo que cada pantalla hace con la respuesta (preseleccionar un SKU, avisar de que
  la lista está vacía).
- `reload()`: para los botones "Actualizar".

**Por qué importa:** la parte delicada (descartar respuestas que llegan tarde, no mostrar errores si
la sesión caducó) está **en un solo sitio**. Si mañana hay que corregirla, se corrige una vez.

### Los demás

| Duplicado | Solución |
|---|---|
| `formRef` + `setFocusField()` idénticos en entrada y salida de stock | Custom Hook **`useFocusField()`** en `app/ui/inventory-ui.tsx` |
| Validación de formularios copiada en `index.html` y `application.html` | Módulo **`trackflow-web/js/form-validation.js`**, cargado por las dos páginas |
| Carga y configuración de Tailwind en cada HTML | Una sola hoja **`css/styles.css`** (además se cachea entre páginas) |
| Clases de pestaña activa/inactiva repetidas 4 veces | Función **`setTabState()`** con los estilos en constantes |

---

## 10. Resultados

Mediana de 3 ejecuciones, mismas condiciones antes y después ([REPORT.md](REPORT.md) tiene la tabla
completa con todas las métricas):

| Página (móvil) | Antes | Después | LCP |
|---|---|---|---|
| Web `/` | 86 / 92 / 100 / 100 | **100 / 100 / 100 / 100** | 3,9 s → **1,5 s** |
| Web `/application` | 97 / 89 / 100 / 100 | **100 / 100 / 100 / 100** | 2,1 s → **0,9 s** |
| Backoffice `/login` | 97 / 100 / 100 / 100 | **98** / 100 / 100 / 100 | 2,7 s → **2,4 s** |
| Backoffice `/` | 95 / 100 / 100 / 100 | **96** / 100 / 100 / 100 | 2,9 s → **2,7 s** |

En escritorio todo queda en 100. De las tres páginas que suspendían el LCP, la web y el login pasan a
"bueno"; el analizador mejora pero sigue en "necesita mejorar" (ver la sección siguiente).

---

## 11. Lo que no se cambió (y por qué)

- **El JavaScript "legacy" y "sin usar" del backoffice.** Lighthouse lo señala, pero está en el código
  del propio Next.js, no en el nuestro. Tocarlo no está en nuestra mano y su impacto en el LCP es 0.
- **El LCP del analizador (2,7 s).** La sesión está en `localStorage`, que solo existe en el navegador:
  el servidor no puede saber si hay sesión, así que la vista protegida solo puede pintarse después de
  cargar y ejecutar el JavaScript. La solución de fondo sería guardar la sesión en una *cookie* y
  comprobarla en el servidor, un cambio de arquitectura de la autenticación que se deja como
  recomendación.
- **Caché HTTP de la web.** Es configuración del servidor de producción (cabeceras `Cache-Control`),
  no del código.
- **Las demás pantallas con cargas parecidas** (proveedores, incidencias, Talent): tienen formas de
  estado distintas (paginación, peticiones encadenadas). `useApiResource` podrá adoptarse ahí más
  adelante, sin mezclarlo con esta auditoría.

---

## 12. Cómo se comprobó que nada se ha roto

| Comprobación | Resultado |
|---|---|
| Suites de UI (`node tests/ui/run.mjs`): web, backoffice, incidencias, proveedores, inventario, talent | **181 / 181** |
| Tests unitarios del backoffice (`npx jest`) | **148 / 148** |
| TypeScript (`npx tsc --noEmit`) | Sin errores |
| ESLint | Sin errores nuevos (2 previos en un archivo que no se ha tocado) |
| Login con `?reset=1` en el navegador | Sigue mostrando "Contraseña actualizada" |
| Capturas de la web compilada | Mismo aspecto que con el CDN |

Los tests de la web se tuvieron que **actualizar**, no porque algo fallara, sino porque comprobaban la
implementación antigua: que existiera el programa del CDN (`window.tailwind`) y que las fotos vinieran
de Unsplash. Ahora comprueban que la hoja compilada está cargada y que las fotos son locales. Y la
web ya no hace **ninguna** petición a dominios externos.

---

## 13. Cómo repetir la auditoría tú solo

**Medición automática (antes/después):**

```sh
node tests/perf/lighthouse.mjs before                    # o after; tarda ~10 minutos
node tests/perf/lighthouse.mjs after backoffice-login    # solo una página
```

Deja el resumen en `docs/lighthouse/<etiqueta>/summary.json` y el informe HTML de cada caso (ábrelo
en el navegador para ver todos los detalles). No necesita nada arrancado: usa sus propios puertos.

**Capturas manuales con DevTools:**

```powershell
docker compose up -d backend                            # terminal 1 (API en :8000)
cd uis\backoffice; npm run build; npm run start         # terminal 2 (:3001)
cd uis\website; npm ci; npm run build; npm run start    # terminal 3 (:3000)
```

Chrome en incógnito → `F12` → Lighthouse → *Navigation* → Mobile y Desktop → *Analyze page load*.
Repite 2–3 veces por página: Performance varía entre ejecuciones.

**Checklist mental de una auditoría:**

1. Mide en **producción** y en **móvil**.
2. Mira primero las **métricas** (LCP, FCP, TBT, CLS), no solo la nota.
3. Para cada métrica que suspende, busca su **elemento** (¿cuál es el LCP?) y su **cadena** (¿qué
   tiene que llegar antes?).
4. Arregla la **causa raíz**, de mayor a menor impacto.
5. **Vuelve a medir igual.** Si no mejora, deshazlo.

---

## 14. Archivos creados y modificados

| Archivo | Cambio |
|---|---|
| `AUDIT.md`, `REPORT.md`, `hito_11.md` | Entregables |
| `.agents/skills/`, `.claude/skills/`, `skills-lock.json` | Skills instaladas (`core-web-vitals`, `performance`, `web-perf`) |
| `tests/perf/lighthouse.mjs` | **Nuevo.** Medición Lighthouse reproducible |
| `docs/lighthouse/` | Resúmenes de las mediciones y capturas (`capturas/antes`, `capturas/despues`) |
| `uis/website/package.json`, `package-lock.json` | Tailwind y `serve`; scripts `build`, `start`, `watch` |
| `uis/website/tailwind.config.js`, `uis/website/src/styles.css` | **Nuevos.** Configuración y entrada de Tailwind |
| `uis/website/trackflow-web/css/styles.css` | **Nuevo (generado).** CSS compilado |
| `uis/website/trackflow-web/img/*.webp` | **Nuevos.** Fotos del carrusel en 3 anchos |
| `uis/website/trackflow-web/js/form-validation.js` | **Nuevo.** Validación compartida |
| `uis/website/trackflow-web/index.html` | CSS compilado, imagen responsive, contraste, puntos del carrusel, validación compartida |
| `uis/website/trackflow-web/application.html` | CSS compilado, ARIA, validación compartida, `setTabState` |
| `uis/backoffice/app/lib/use-api-resource.ts` | **Nuevo.** Custom Hook de carga de datos |
| `uis/backoffice/app/ui/inventory-ui.tsx` | Custom Hook `useFocusField` |
| `uis/backoffice/app/(protected)/inventory/**` | Las 4 pantallas usan los hooks |
| `uis/backoffice/app/(auth)/login/page.tsx` | Suspense solo alrededor del aviso de `?reset=1` |
| `uis/backoffice/app/layout.tsx` | Sin Geist Mono |
| `uis/backoffice/next.config.ts`, `uis/backoffice/.gitignore` | `distDir` configurable (para que el script mida sin pisar tu `next start`) |
| `uis/start.sh`, `uis/Dockerfile` | Tailwind en modo *watch* en el contenedor de desarrollo |
| `.dockerignore`, `uis/.dockerignore` | Excluyen la carpeta de build del script (`.next-lighthouse`) |
| `tests/ui/website.mjs`, `tests/ui/lib/harness.mjs`, `tests/ui/README.md` | Tests de la web adaptados a CSS compilado e imágenes locales |
| `README.md`, `docs/trackflow-web/README.md`, `uis/website/trackflow-web/README.md` | Stack y comandos actualizados |

---

## 15. Glosario

| Término | Significado |
|---|---|
| **Auditoría** | Medir, comparar con umbrales, encontrar la causa raíz, corregir y volver a medir |
| **Lighthouse** | Herramienta de Google que puntúa una página en Performance, Accessibility, Best Practices y SEO |
| **Core Web Vitals** | LCP, INP y CLS: las métricas con las que Google valora la experiencia |
| **FCP** | Cuándo se pinta lo primero |
| **LCP** | Cuándo se pinta lo más grande de la pantalla |
| **TBT** | Tiempo en que el hilo principal está bloqueado por JavaScript |
| **CLS** | Cuánto se mueve el contenido mientras carga |
| **INP** | Lo que tarda la página en responder a una interacción (solo en datos reales) |
| **Laboratorio / campo** | Medición simulada en un equipo (Lighthouse) / datos de usuarios reales (CrUX, RUM) |
| **Throttling** | Ralentizar a propósito red y CPU para imitar un móvil |
| **Lantern** | Modelo con el que Lighthouse simula la carga lenta a partir de una carga rápida |
| **Ruta crítica** | Ficheros que hay que descargar sí o sí antes de ver la página |
| **Render-blocking** | Recurso que impide pintar hasta que llega (CSS, scripts sin `defer`) |
| **Build** | Paso que prepara el código para producción (compilar, minificar, generar HTML estático) |
| **Minificar** | Quitar espacios y acortar nombres para que el fichero pese menos |
| **Hidratación** | Cuando React toma el control del HTML que mandó el servidor y lo hace interactivo |
| **Prerender / HTML estático** | Página generada en el build, que el servidor envía tal cual |
| **Suspense** | Componente de React que muestra un *fallback* mientras lo de dentro no puede pintarse |
| **`srcset` / `sizes`** | Atributos de `<img>` para ofrecer varias versiones y que el navegador elija |
| **WebP / AVIF** | Formatos de imagen modernos, más ligeros que JPEG |
| **`fetchpriority`** | Pista al navegador sobre qué recurso es más importante |
| **Contraste** | Relación de luminosidad entre texto y fondo; WCAG AA pide 4,5:1 |
| **ARIA** | Atributos que explican a los lectores de pantalla qué es cada elemento |
| **Custom Hook** | Función `use…` propia que reutiliza lógica con estado entre componentes de React |
| **Skill de agente** | Paquete de instrucciones que guía a un agente de IA en una tarea concreta |
| **Mediana** | El valor del medio al ordenar varias mediciones; resiste mejor el ruido que la media |
