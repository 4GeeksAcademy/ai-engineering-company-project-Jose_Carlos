# Hito 13 · Optimización de rendimiento con caching (frontend + backend)

> Documento de aprendizaje. Está escrito para alguien que **no sabe nada** de rendimiento ni de caché
> y quiere entender, como desarrollador, qué se ha hecho en TrackFlow, **por qué** y **cómo defenderlo**.
> Se va completando fase a fase. El informe técnico corto es `CACHING_REPORT.md` (Fase 4).

Rama de trabajo: `feature/caching-optimisation` (sin commits: los hace Jose Carlos).

---

## 0. Las ideas básicas, explicadas desde cero

### 0.1 ¿Qué es la "latencia"?
Es el tiempo que pasa desde que alguien pide algo hasta que recibe la respuesta. En una API:
el navegador manda `GET /inventory/products` y la latencia es lo que tarda en volver la lista.
Se mide en **milisegundos (ms)**: 1000 ms = 1 segundo. Como referencia:

| Latencia | Cómo lo percibe una persona |
|---|---|
| < 100 ms | Instantáneo |
| 100–300 ms | Rápido, pero se nota |
| 300–1000 ms | "Está pensando" |
| > 1 s | Lento; la persona pierde el hilo |

### 0.2 ¿De dónde sale el tiempo de una petición en TrackFlow?
Una petición a la API pasa por varias fases y **cada una cuesta tiempo**:

1. **Red navegador → API** (en local, casi 0).
2. **Autenticación**: comprobar el JWT y buscar el usuario en TinyDB.
3. **Base de datos**: aquí está casi todo el coste.
   - **TinyDB** es un archivo JSON en el disco: leerlo es rápido mientras sea pequeño, pero
     TinyDB **relee el archivo entero en cada operación**.
   - **Supabase** es PostgreSQL **en la nube**. Cada consulta tiene que viajar por Internet
     hasta el servidor de Supabase y volver: hemos medido **~50 ms por viaje** ("round-trip").
     Si un endpoint hace 10 consultas seguidas, son 500 ms solo de viajes.
4. **Cálculo en Python** (sumar, ordenar, convertir a JSON).
5. **Red API → navegador** (proporcional al tamaño de la respuesta).

### 0.3 ¿Qué es una caché?
Guardar el **resultado** de un trabajo caro para no repetirlo. Ejemplo de la vida real: si te
preguntan 50 veces al día cuántos palés hay en el muelle 3, no vas a contarlos cada vez; los
cuentas una vez, apuntas el número en una pizarra y respondes leyendo la pizarra. Hasta que
llega un camión (una **escritura**): entonces borras la pizarra (**invalidas**) y vuelves a contar.

Vocabulario:
- **HIT** (acierto): el dato estaba en la caché → respuesta inmediata.
- **MISS** (fallo): no estaba (o había caducado) → se calcula de verdad y se guarda.
- **TTL** (*time to live*, tiempo de vida): cuántos segundos vale un dato guardado. Pasado ese
  tiempo, se considera caducado y la siguiente petición es un MISS.
- **Invalidar**: borrar a propósito una entrada porque sabemos que el dato ha cambiado.
- **Clave** (*key*): el "nombre" con el que se guarda cada resultado, p. ej.
  `GET /inventory/products`. Dos peticiones con la misma clave comparten la misma respuesta
  guardada… y por eso la clave es **crítica para la seguridad** (ver 0.5).

### 0.4 El precio de una caché: la frescura
Una caché **siempre** puede devolver un dato algo antiguo ("desactualizado", *stale*). Es un
intercambio: ganas velocidad y pagas con frescura. Por eso no se cachea todo, sino lo que cumple
a la vez:

> **coste alto** (tarda mucho) × **frecuencia alta** (se pide mucho) × **estabilidad** (cambia poco
> o sabemos exactamente cuándo cambia)

### 0.5 El peligro: fugas de datos
Si el endpoint devuelve datos **del usuario que pregunta** (su perfil, por ejemplo) y la clave
de caché no incluye su ID, el segundo usuario recibiría **los datos del primero**. Es una fuga
de datos. Regla: si la respuesta depende de quién pregunta, el ID va en la clave; si no se puede
acotar con seguridad, **no se cachea**.

### 0.6 En el frontend: lazy loading y `useMemo`
- **Lazy loading** (carga diferida): el navegador descarga JavaScript antes de poder mostrar la
  página. Si un trozo de interfaz solo aparece cuando el usuario pulsa un botón (un formulario
  que se despliega), su código puede descargarse **en ese momento** y no en la carga inicial.
  En Next.js se hace con `next/dynamic`.
- **`useMemo`**: React vuelve a ejecutar la función del componente en cada *render* (cada vez
  que cambia cualquier estado, por ejemplo al escribir una letra en un input). Si dentro hay un
  cálculo caro (ordenar 750 SKUs), se repite en cada pulsación. `useMemo` guarda el resultado y
  solo lo recalcula cuando cambian sus **dependencias**. Es una caché, pero dentro de un componente.

---

## 1. Fase 1 · Medir antes de tocar nada

**Regla de oro de la optimización: primero se mide, luego se decide.** Sin datos, "optimizar" es
adivinar, y lo habitual es cachear lo que no hacía falta y dejar lo importante igual.

### 1.1 Comprobación previa
Antes de cambiar nada se comprobó que todo funcionaba:
- Backend: `uv run uvicorn services.api.main:app --port 8000` arranca y conecta con Supabase.
- Frontend: `npx next build` en `uis/backoffice` compila sin errores (19 rutas).

### 1.2 Cambio: middleware de timing — `services/api/main.py`

**Qué es un middleware**: una función que envuelve **todas** las peticiones. FastAPI la ejecuta
antes del endpoint y recibe la respuesta al terminar. Es el sitio perfecto para cronometrar.

```python
logger = logging.getLogger("api.timing")
if not logger.handlers:
    _timing_handler = logging.StreamHandler()
    _timing_handler.setFormatter(logging.Formatter("%(levelname)s:     [%(name)s] %(message)s"))
    logger.addHandler(_timing_handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


@app.middleware("http")
async def timing_middleware(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)          # aquí se ejecuta el endpoint
    duration = (time.perf_counter() - start) * 1000  # ms
    logger.info(f"{request.method} {request.url.path} → {response.status_code} | {duration:.1f}ms")
    return response
```

Por qué cada pieza:
- `time.perf_counter()` y no `time.time()`: es un reloj pensado para medir intervalos, con mucha
  precisión, y no salta si el sistema cambia la hora.
- `await call_next(request)`: "deja pasar" la petición al endpoint y espera su respuesta.
- **El handler de logging**: uvicorn solo configura *sus* loggers. Un logger nuevo
  (`api.timing`) no tiene dónde escribir y, por defecto, Python solo muestra mensajes de nivel
  WARNING o superior: los `INFO` se perderían. Por eso se le añade un `StreamHandler` (escribe en
  la consola) con nivel INFO. `propagate = False` evita que el mensaje salga duplicado si algún
  día se configura el logger raíz. El `if not logger.handlers` evita añadir el handler dos veces
  si el módulo se importa más de una vez (pasa con `--reload` y en los tests).

Resultado en consola:
```
INFO:     [api.timing] GET /inventory/products → 200 | 279.9ms
```

> Nota Windows: si rediriges la salida a un archivo, pon `PYTHONIOENCODING=utf-8` para que la
> flecha `→` no dé error de codificación (en la consola y en Docker no hace falta).

### 1.3 Cambio: seeder de volumen — `services/seed_perf.py` (nuevo)

**Por qué hace falta**: con 6 SKUs y 12 movimientos todo es rápido y no hay nada que optimizar.
En producción, un 3PL acumula miles de movimientos al año. Hay que medir con un volumen parecido
al real, o las conclusiones no valen.

**Por qué con calidad y no "10.000 filas iguales"**: las bases de datos y los algoritmos se
comportan distinto con datos variados. Si todos los SKUs fueran del mismo almacén, un filtro por
almacén no filtraría nada; si todas las fechas fueran iguales, ordenar sería trivial. Los datos
tienen que "costar trabajo" de verdad.

Qué genera (ver el docstring del script para el detalle):
- **36 marcas cliente ficticias** (moda, electrónica, cosmética), las de EE. UU. en Los Ángeles,
  las europeas en Zaragoza y algunas en los dos almacenes.
- **753 SKUs** con variantes reales (talla, color, capacidad): `STL-RUN-BLK-42 · Zapatilla running negro - 42`.
- **Un año de movimientos simulados día a día**: despachos solo si hay stock, reposición cuando el
  stock baja del punto de pedido, mermas, estacionalidad (Black Friday/Navidad ×2,3; domingos casi
  sin actividad), números de seguimiento con el formato de cada transportista (UPS `1Z…`, USPS
  `9400…`, SEUR, Correos Express, GLS, DHL Parcel).
- **1.200 incidencias** que citan SKUs, marcas, transportistas y seguimientos que existen en el seed.

Decisiones de seguridad:
- **Una sola transacción** para el inventario: o se escribe todo, o nada.
- Antes del commit se recalcula el stock con la **misma función que usa la API**
  (`inventory_service.stock_levels`): si algún SKU quedara negativo, se deshace todo.
- **Reversible**: `--purge` borra solo lo que creó este seed (por nombre de marca, que es
  ficticio y único; y por la tabla `perf_seed_incidents` para las incidencias).
- **Semilla fija** (`random.Random(13)`): siempre genera exactamente los mismos datos, así las
  mediciones se pueden repetir.
- **Inserción por lotes** (`INSERT ... VALUES` de 2.000 filas): con 50 ms por viaje a Supabase,
  insertar fila a fila serían 22.000 × 50 ms ≈ 18 minutos; por lotes son unos segundos.

> **Incidente durante el desarrollo (y lección)**: la primera prueba con `--dry-run` *sí* escribió
> datos, porque el `return` que debía cortar la ejecución no llegó a insertarse en el código (un
> reemplazo de texto falló sin avisar) y además con una configuración de demanda que generaba
> ~186.000 salidas. Se detectó porque el seed real se negó a ejecutarse ("ya existen"). Se corrigió
> el `--dry-run`, se comprobó que ya no escribe nada y se usó `--purge` para volver exactamente al
> estado inicial (6/8/4 filas, 95 incidencias). Lección: **una opción "no escribe nada" hay que
> probarla contando filas antes y después**, no darla por buena.

### 1.4 Cambio: script de medición — `scripts/bench_api.py` (nuevo)

Inicia sesión y lanza **la misma URL, con los mismos parámetros, N veces** contra cada endpoint
de lectura. Guarda la primera petición aparte (con caché será el MISS) y la mediana del resto.

Por qué la **mediana** y no la media: si de 10 peticiones una tarda 3 segundos por un hipo de la
red, la media se dispara y deja de representar lo normal. La mediana (el valor del medio) no se
deja arrastrar por un caso raro. El **p95** (el 95 % de las peticiones tardó menos que esto) nos
dice cómo de malo es el peor caso habitual.

### 1.5 Filas por tabla, antes y después del seed

| Tabla | Antes | Después |
|---|---:|---:|
| `sku` (Supabase) | 6 | 759 |
| `stock_entry` (Supabase) | 8 | 1.451 |
| `stock_exit` (Supabase) | 4 | 21.023 |
| `incidents` (TinyDB) | 95 | 1.295 |
| `incident_embeddings` (TinyDB) | 95 | 1.295 |
| `suppliers` (TinyDB) | 15 | 15 |

Tamaño de los archivos TinyDB: `db.json` pasó de 53 KB a 717 KB y `db.embeddings.json` a 5,4 MB.

### 1.6 Resultados del backend (mediana de 10 peticiones idénticas, ms)

Resultados completos en `docs/caching/bench-antes-seed.json` y `docs/caching/bench-con-seed.json`.

| Endpoint | Antes del seed | Con seed | Tamaño respuesta |
|---|---:|---:|---:|
| `GET /auth/me` | 3,6 | 20,3 | 0,2 KB |
| `GET /suppliers` | 3,4 | 16,8 | 4,7 KB |
| `GET /api/incidents` | 4,6 | 30,9 | 472 KB |
| `GET /api/incidents/summary` | 5,8 | 18,8 | 0,4 KB |
| `GET /api/incidents/duplicates` | 14,5 | **235,3** | 2,8 KB |
| `GET /api/incidents/search?q=…` | 25,4 | 239,7 | 8,1 KB |
| `GET /api/incidents/1/similar` | 26,1 | 248,2 | 1,1 KB |
| `GET /api/incidents/semantic-status` | 7,7 | 119,1 (1ª: 3.011) | 0,1 KB |
| `GET /inventory/products` | 279,9 | **380,3** (1ª: 1.454) | 163 KB |
| `GET /inventory/products/1` | 272,3 | 276,1 | 0,2 KB |
| `GET /inventory/orders` | 539,7 | **42.557** | 7,1 MB |

Qué nos dicen estos números (la parte importante, más que las cifras):

1. **Los endpoints de TinyDB pasaron de ~3,5 ms a ~20 ms sin que cambiara su código.** Incluso
   `/auth/me`, que no tiene nada que ver con incidencias. ¿Por qué? Porque toda petición
   autenticada busca el usuario en TinyDB, y TinyDB **relee el archivo `db.json` completo** en cada
   operación. Al añadir 1.200 incidencias, el archivo creció 13 veces, y cada petición paga leerlo.
   Lección: en una base de datos de archivo, los datos de una tabla ralentizan a las demás.
2. **Los endpoints semánticos (duplicados, búsqueda, similares) pasaron de ~20 ms a ~240 ms**:
   cada llamada relee los 5,4 MB de embeddings y monta una matriz de 1.295 vectores. La primera
   llamada a `semantic-status` tarda 3 s porque carga el modelo de IA en memoria (pasa una vez por
   arranque; no es algo que arregle una caché).
3. **`/inventory/products` tarda ~380 ms**: tres consultas a Supabase (~50 ms de viaje cada una
   más la que hace `pool_pre_ping`) y dos de ellas suman las 22.000 filas de movimientos con
   `SUM ... GROUP BY`. La primera vez tardó 1,5 s porque PostgreSQL aún no tenía esas páginas en
   su memoria.
4. **`/inventory/orders` pasó de 0,5 s a 42,5 s.** Con el contador de consultas SQL se vio por qué:
   lanza **761 consultas** (2 para traer los movimientos + **una por cada SKU** para leer sus datos).
   Esto se llama **problema N+1**: el código pide "dame los movimientos" (1 consulta) y luego, al
   convertir cada movimiento a JSON, accede a `order.sku`, y SQLAlchemy va a buscar ese SKU a la base
   de datos (N consultas). Con 759 SKUs × ~55 ms = ~42 s. **Una caché no arregla esto**: el primer
   usuario tras cada invalidación seguiría esperando 42 s. Lo correcto es cargar los SKUs en una sola
   consulta extra (`selectinload`) y, encima, si compensa, cachear.

### 1.7 Resultados del frontend

**Tamaño de JavaScript por ruta** (`next build`, extraído de `.next/diagnostics/route-bundle-stats.json`,
porque Next 16 con Turbopack ya no imprime la tabla de tamaños en consola):

- Todas las rutas comparten **461 KB** (138 KB gzip): React, React DOM y el runtime de Next.
- Lo propio de cada ruta va de 20 KB (login) a 67 KB (`/talent/records/[id]`). Las rutas protegidas
  comparten además un chunk de 35 KB (guard de sesión, cabecera, cliente de la API).
- **No hay ninguna librería pesada** (ni gráficos, ni mapas, ni editores): `package.json` solo tiene
  `next`, `react` y `react-dom`. Por eso el margen de mejora con lazy loading es **pequeño** y hay
  que decirlo así: aquí no hay un "gráfico de 200 KB" que quitar de la carga inicial.

**Cálculos en cada render** (medidos en Node con los datos reales de la API: 759 SKUs, 22.474 movimientos):

| Cálculo | Dónde | Coste por render |
|---|---|---:|
| Ordenar SKUs con `localeCompare("es")` y agruparlos por almacén | `SkuOptions` (formularios de entrada y salida) | 1,53 ms + crear 759 `<option>` |
| Filtrar movimientos con búsqueda de texto | `OrdersClient` | 4,30 ms |
| Filtrar movimientos sin búsqueda + contar entradas | `OrdersClient` | 0,43 ms |
| Filtrar SKUs + calcular niveles | `ProductsClient` | 0,06 ms |

(En un portátil normal o un móvil, estos tiempos pueden ser de 2 a 4 veces mayores.)

### 1.8 La propuesta que se aprobó (checkpoint)

Con estas medidas se propuso, y Jose Carlos aprobó, lo siguiente:

- **Cachear** `GET /inventory/products` (TTL 60 s) y `GET /api/incidents/duplicates` (TTL 300 s).
- **Arreglar el N+1** de `GET /inventory/orders` y, con la medida nueva, decidir si también se cachea.
- **Lazy loading** de los dos formularios del Talent Pipeline que solo aparecen al pulsar un botón,
  y **`useMemo`** en `SkuOptions`.
- **Descartados**: `/auth/me` y los perfiles (datos de cada usuario, rápidos, sin ganancia que
  compense el riesgo), `/suppliers` (17 ms), `search` y `similar` (cada consulta es distinta: casi
  nunca habría HIT), y `useMemo` en `ProductsClient` y `OrdersClient` (0,06 y 0,43 ms: memoizar
  costaría más complejidad de lo que ahorra).

---

## 2. Fase 2 · Frontend

### 2.1 Antes de nada: Server Components y Client Components

En el App Router de Next.js hay dos tipos de componente, y la diferencia importa para el lazy loading:

| | Server Component | Client Component |
|---|---|---|
| Cómo se marca | Es el tipo por defecto | El archivo empieza por `"use client"` |
| Dónde se ejecuta | Solo en el servidor; al navegador llega el HTML resultante | En el servidor (para el primer HTML) **y** en el navegador |
| ¿Su código viaja al navegador? | **No** | **Sí**: es el JavaScript que hay que descargar |
| ¿Puede usar `useState`, `onClick`, `window`…? | No | Sí |

En TrackFlow, los `page.tsx` son Server Components muy finos (ponen el `<title>` con `metadata` y
pintan un componente), y toda la pantalla es un Client Component. Ejemplo,
`app/(protected)/talent/page.tsx`:

```tsx
export const metadata: Metadata = { title: "Talent Pipeline", ... };   // solo servidor
export default function TalentHome() {
  return <Suspense ...><HomeClient /></Suspense>;                       // HomeClient es "use client"
}
```

Consecuencia: **el lazy loading solo tiene sentido en Client Components**, porque son los únicos
cuyo código se descarga. Un Server Component ya no manda JavaScript al navegador; no hay nada que
diferir. Por eso los dos `next/dynamic` se declaran dentro de `home-client.tsx` y
`record-detail-client.tsx`, que son `"use client"`.

### 2.2 Cambio: lazy loading del formulario "Nueva candidatura"

**Archivos**: `uis/backoffice/app/ui/candidate-create-form.tsx` (nuevo), `uis/backoffice/app/ui/home-client.tsx` (modificado).

**Qué**: el formulario (9 campos) estaba escrito dentro de `HomeClient`. Lo moví tal cual a su propio
archivo, como un componente que solo pinta (el estado sigue en `HomeClient` y le llega por props), y
`HomeClient` lo importa así:

```tsx
const CandidateCreateForm = dynamic(
  () => import("./candidate-create-form").then((module) => module.CandidateCreateForm),
  { loading: () => <FormSkeleton fields={9} className="mt-4 space-y-3" /> },
);
```

**Por qué este componente**: solo se ve si alguien pulsa "Nueva candidatura". La mayoría de visitas a
`/talent` son para buscar y consultar; no tiene sentido que todos descarguen el formulario de alta.

**Cómo funciona**: `import()` (con paréntesis) es un import *dinámico*: el empaquetador saca ese archivo
a un **chunk** (un archivo `.js`) aparte, y el navegador solo lo pide cuando React intenta pintar
`<CandidateCreateForm>` por primera vez, es decir, al pulsar el botón. Mientras llega, se pinta lo
que devuelve `loading`.

**Por qué el `import type`**: `HomeClient` necesita el *tipo* `CreateFormState` del nuevo archivo. Con
`import type`, TypeScript lo usa para comprobar tipos y lo borra al compilar; con un `import` normal,
el empaquetador metería el archivo entero en el chunk inicial y el lazy loading no serviría de nada.

### 2.3 Cambio: lazy loading del formulario de edición del perfil

**Archivos**: `uis/backoffice/app/ui/profile-edit-form.tsx` (nuevo),
`uis/backoffice/app/(protected)/talent/records/[id]/record-detail-client.tsx` (modificado).

Mismo patrón: el formulario de 7 campos que aparece al pulsar "Editar" en el detalle de una
candidatura. La mayoría de visitas al detalle son para leerlo, cambiar el estado o añadir notas.

Comprobé con un script que el JSX extraído en los dos archivos nuevos es **idéntico** al original
(cambiando solo los nombres de las props): es un movimiento, no una reescritura.

### 2.4 Cambio: el `loading` coherente con el diseño — `uis/backoffice/app/ui/form-skeleton.tsx` (nuevo)

Mientras se descarga el chunk se ve un "esqueleto": rectángulos con el mismo borde cian, el mismo
radio y **la misma altura** que los inputs reales (38 px), con una animación suave (`animate-pulse`).
Así, cuando aparece el formulario de verdad, nada salta de sitio (eso se llama *layout shift*). Lleva
`role="status"` y `aria-label="Cargando formulario"` para que un lector de pantalla anuncie qué pasa.
Lo comparten los dos formularios.

### 2.5 ¿Por qué no `ssr: false`?

`ssr: false` le dice a Next: "este componente no lo pintes nunca en el servidor". Solo hace falta
cuando el componente usa algo que **solo existe en el navegador** al pintarse (`window`,
`localStorage`, una librería de mapas que toca el DOM). Si no, el servidor fallaría al intentar pintarlo.

Aquí no se usa porque:
1. Los formularios son inputs normales: no tocan ninguna API del navegador al pintarse.
2. Empiezan cerrados (`isCreateOpen` / `isEditingProfile` valen `false` al cargar), así que el
   servidor **nunca** los pinta de todas formas. Añadir `ssr: false` no cambiaría nada y sería una
   opción "por si acaso" que confunde a quien lea el código.

### 2.6 Cambio: `useMemo` en `SkuOptions` — `uis/backoffice/app/ui/inventory-ui.tsx`

`SkuOptions` pinta las opciones del selector de SKU en los formularios de **entrada** y **salida** de
stock: copia los 759 SKUs, los ordena por nombre con `localeCompare("es")`, los agrupa por almacén y
crea 759 `<option>`. Medido: **~1,5 ms por render**.

El problema: ese formulario se vuelve a pintar **con cada tecla** (cantidad, referencia, número de
seguimiento…), y cada vez se repetía todo el trabajo aunque la lista de SKUs no hubiera cambiado.
Escribir un número de seguimiento de 18 caracteres = 18 × 1,5 ms tirados, más en un portátil lento.

```tsx
const groups = useMemo(() => {
  const sorted = [...skus].sort(...);
  ...
  return result;
}, [skus]);
```

**Las dependencias `[skus]` son completas**: dentro de la función solo se usan `skus` (la prop) y
cosas que nunca cambian (`WAREHOUSE_NAMES`, `warehouseName`, `skuOptionLabel`, que son constantes y
funciones de módulo). Si faltara una dependencia que sí cambia, el componente mostraría datos viejos.

**Por qué funciona aquí**: `useMemo` compara las dependencias por *referencia* (¿es el mismo array?,
no ¿tiene el mismo contenido?). `skus` es el estado que guarda `useApiResource`: es el **mismo** array
en todos los renders hasta que se recarga el catálogo. Si `skus` se creara nuevo en cada render (por
ejemplo `skus.filter(...)` en el padre), el `useMemo` recalcularía siempre y no serviría de nada. Lo
comprobé antes de aplicarlo.

### 2.7 Resultado medido (`next build`)

| Ruta | JS propio antes | Después | Diferencia |
|---|---:|---:|---:|
| `/talent` | 62,9 KB (21,2 KB gzip) | 65,1 KB (22,3 KB gzip) | **+2,2 KB** (+1,1 gzip) |
| `/talent/records/[id]` | 66,9 KB (22,0 KB gzip) | 69,5 KB (23,2 KB gzip) | **+2,6 KB** (+1,2 gzip) |
| Chunk diferido "Nueva candidatura" | — | 2,9 KB (0,8 KB gzip) | solo al abrirlo |
| Chunk diferido "Editar perfil" | — | 2,6 KB (0,8 KB gzip) | solo al abrirlo |

**La carga inicial ha crecido, no bajado.** Lo investigué buscando en los chunks generados: el
formulario sí salió a un chunk aparte (~2,7 KB), pero para hacer `next/dynamic` funcionar, Turbopack
mete en el chunk de la ruta su propio código de soporte (`BailoutToCSR`, `PreloadChunks`, el
envoltorio que gestiona el `loading`), unos 5 KB. **El código de soporte pesa más que lo que se ahorra.**

Lección importante (y por eso no lo escondo): **el lazy loading tiene un coste fijo**, y solo compensa
cuando lo que se difiere es más grande que ese coste: una librería de gráficos, un editor de texto
enriquecido, un mapa, un visor de PDF… TrackFlow no tiene ninguna (ya lo vimos en 1.7: solo `next`,
`react` y `react-dom`). Los formularios cumplen el requisito de la tarea y dejan el patrón listo para
cuando llegue una librería pesada, pero en bytes, hoy, el balance es de +1,1 KB gzip por ruta. Si
fuera una decisión de producto real, yo no lo aplicaría a estos formularios.

El `useMemo` no cambia el tamaño (~0 KB): su ganancia es de CPU en cada pulsación, no de descarga.

### 2.8 Verificación

- `tsc --noEmit`: sin errores. `eslint`: los mismos 2 errores que ya había antes de los cambios, en
  líneas no tocadas de `record-detail-client.tsx` (comprobado lanzándolo sobre la versión original).
- Jest: 148/148. Arnés de UI en Chrome: **Talent 37/37** (incluye abrir y cerrar el formulario de alta,
  que ahora llega por `next/dynamic`) e **Inventario 40/40** (usa `SkuOptions` en entrada y salida).

---

## 3. Fase 3 · Backend

### 3.1 Cambio: arreglo del N+1 — `services/inventory_service.py`

```python
entries = db.exec(select(StockEntry).options(selectinload(StockEntry.sku))).all()
exits = db.exec(select(StockExit).options(selectinload(StockExit.sku))).all()
```

`selectinload(StockEntry.sku)` le dice a SQLAlchemy: "cuando traigas los movimientos, trae **también**
sus SKUs, todos de golpe, con una consulta `SELECT ... FROM sku WHERE id IN (1, 2, 3, ...)`". Así,
cuando el router lee `order.sku`, el dato ya está en memoria y no se lanza ninguna consulta más.

| | Antes | Después |
|---|---:|---:|
| Sentencias SQL por petición | 761 | 6 |
| Mediana de `GET /inventory/orders` | 42.557 ms | 2.131 ms |

**20 veces más rápido sin caché.** Lo primero era arreglar el código: una caché encima de un N+1 solo
habría escondido el problema, y el primer usuario tras cada invalidación seguiría esperando 42 s.

Los 2,1 s que quedan los desglosé con un script: ~1,7 s en traer 22.474 filas de Supabase y montar los
objetos, ~0,3 s en convertirlos a schemas y ~0,07 s en generar el JSON (7 MB). Con ese reparto, **sí**
compensa cachear (3.4).

### 3.2 Cambio: el módulo de caché — `services/api/cache.py` (nuevo)

Por qué en `services/api/`: ahí viven las piezas transversales de la API (`security.py`, `store.py`,
`errors.py`). La tarea sugería `app/core/cache.py`, pero ese directorio no existe en este proyecto y
crearlo rompería la estructura.

**Estructura**: un diccionario `clave → (valor, instante de caducidad)`.

```python
self._entries: dict[str, tuple[object, float]] = {}
```

**Las piezas, una a una:**

- `set(key, value, ttl_seconds)`: **el TTL es obligatorio** (no tiene valor por defecto) y si es 0 o
  negativo lanza `ValueError`. Así es imposible crear una entrada que no caduque nunca por descuido.
- `get(key)`: si la entrada existe y no ha caducado → **HIT**. Si no existe, o ha caducado (se borra en
  ese momento) → **MISS**. Devuelve un objeto especial `_MISSING` en vez de `None`, porque `None` o `[]`
  pueden ser respuestas válidas (una lista sin duplicados es `[]`, y también hay que cachearla).
- `get_or_set(key, ttl, compute)`: el uso normal. Mira la caché; si es MISS, llama a `compute()`, guarda
  y devuelve. **Si `compute()` lanza una excepción, no se guarda nada**: un error no se cachea (si
  Supabase falla un instante, no queremos servir ese error durante 60 s).
- `invalidate(key)` e `invalidate_prefix(prefix)`: borran una clave, o todas las que empiezan por un
  prefijo (`/inventory/` borra productos, histórico y lo que se cachee ahí en el futuro).
- **Logs**: cada operación escribe `HIT`, `MISS` o `INVALIDATE` con la clave, en el logger `api.cache`.

**El lock (`threading.Lock`)**. Las rutas de FastAPI escritas con `def` (no `async def`), como todas
las de TrackFlow, se ejecutan en un *threadpool*: **varios hilos a la vez**. Si dos peticiones tocan el
diccionario al mismo tiempo (una leyendo, otra borrando por un `invalidate_prefix` que lo recorre),
Python puede lanzar `RuntimeError: dictionary changed size during iteration` o leer una entrada a
medias. El `with self._lock:` hace que solo un hilo a la vez toque el diccionario.

Detalle importante: **el cálculo caro (`compute()`) va fuera del lock**. Si fuera dentro, mientras se
calculan los 2 s del histórico, ninguna otra petición podría ni siquiera leer la caché de productos.
El precio de esa decisión: si dos peticiones llegan a la vez con la caché vacía, las dos calculan (lo
que se llama *cache stampede*). Con un solo worker y este tráfico es aceptable; está anotado en el informe.

**El reloj (`time.monotonic`)**. No uso `time.time()` (la hora del sistema) porque puede saltar hacia
atrás o adelante (cambio de hora, sincronización NTP) y caducar entradas de golpe o alargarlas. El reloj
monotónico solo avanza. Además está en una variable de módulo (`_clock`) que los tests sustituyen por un
reloj manual: así se comprueba la caducidad "avanzando 60 segundos" sin esperar 60 segundos de verdad.

**Por qué no `functools.lru_cache`** (lo prohibía la tarea, y con razón): no tiene TTL (un dato se
quedaría para siempre), no se puede invalidar una clave concreta (solo vaciarla entera), y cachea por
los argumentos de la función: la sesión de base de datos `db` es un objeto distinto en cada petición,
así que nunca habría HIT.

### 3.3 Las claves — `make_key(path, params, scope)`

```python
make_key("/api/incidents", {"status": "open", "branch": "central"})
# → "/api/incidents?branch=central&status=open"
```

- Los parámetros se **ordenan**: `?status=open&branch=central` y `?branch=central&status=open` son la
  misma consulta y deben compartir entrada.
- Se **normalizan**: se recortan espacios y se descartan los vacíos (`?category=` es lo mismo que no
  mandarlo). Sin esto, la misma petición escrita de dos formas ocuparía dos entradas.
- `scope`: si la respuesta depende de quién pregunta, su id va en la clave: `"/auth/me|scope=user-1"`.
  Va **al final** a propósito: así `invalidate_prefix("/auth/me")` borra la de todos los usuarios.

**Los endpoints cacheados no llevan `scope`, y es seguro**: el catálogo, el histórico de movimientos y
los grupos de duplicados son **iguales para cualquier usuario con sesión** (el backoffice no filtra por
usuario ni por cliente: todos los empleados ven todo el inventario y todas las incidencias). Lo que sí
importa es que **la autenticación va antes que la caché**: es una dependencia del router
(`dependencies=[Depends(get_current_user)]`), y FastAPI la ejecuta antes de entrar en la función.
Sin token válido → 401, y nunca se llega a mirar la caché. Hay un test que lo comprueba.

Estos tres endpoints no tienen parámetros de consulta, así que su clave es una constante
(`INVENTORY_PRODUCTS_CACHE_KEY = make_key("/inventory/products")`). Si algún día se les añade un filtro,
habrá que pasarlo a `make_key`; si no, todos los filtros compartirían la misma respuesta.

### 3.4 Cambio: aplicar la caché — `services/routers/inventory.py` y `services/api/routes/incidents.py`

| Endpoint | TTL | Constante | Se invalida con |
|---|---:|---|---|
| `GET /inventory/products` | 60 s | `INVENTORY_PRODUCTS_TTL_SECONDS` | `POST /inventory/products`, `POST /inventory/orders/inbound`, `POST /inventory/orders/outbound` |
| `GET /inventory/orders` | 120 s | `INVENTORY_ORDERS_TTL_SECONDS` | las mismas tres escrituras |
| `GET /api/incidents/duplicates` | 300 s | `INCIDENT_DUPLICATES_TTL_SECONDS` | `POST /api/incidents`, `PATCH /api/incidents/{id}/status` |

**Por qué estos TTL** (cada constante lleva este razonamiento en un comentario en el código):

- **Productos, 60 s**: es el dato más "vivo" (el stock). Pero el operario que registra una entrada la
  ve **al instante**, porque su escritura invalida. El TTL solo afecta a lo que no pasa por esta API
  (otro proceso, un script, el seed): en el peor caso, un minuto de retraso. ¿Y si el stock mostrado
  está desfasado y alguien intenta sacar más de lo que hay? **No pasa nada grave**: `register_exit`
  bloquea la fila del SKU y vuelve a calcular el stock **contra la base de datos**, sin caché. La caché
  solo afecta a lo que se *ve*, nunca a la regla de negocio "el stock no puede quedar negativo".
- **Histórico, 120 s**: es un registro de lo que ya pasó, no una decisión en tiempo real, y es lo más
  caro (2,1 s y 38,5 MB de memoria). Las escrituras propias se ven al instante igualmente.
- **Duplicados, 300 s**: es un panel de revisión ("mira, estas parecen la misma incidencia"), no una
  alarma. Cinco minutos de retraso, solo para lo que llegue por otra vía, es razonable.

**Cómo se invalida**: justo **después** de que la escritura se haya guardado bien, y solo entonces:

```python
response_cache.invalidate_prefix(INVENTORY_CACHE_PREFIX)   # después de register_entry, que ya hizo commit
return StockEntryRead.model_validate(entry)
```

Si la escritura falla (stock insuficiente → 400, SKU inexistente → 404, código duplicado → 409), la
excepción sale antes y **no se invalida**: nada ha cambiado, la caché sigue siendo válida. Hay un test
para el caso de la salida rechazada.

Con duplicados hay una sutileza: al crear una incidencia, su embedding se calcula **después** de
responder (tarea en segundo plano). ¿Podría la caché guardar unos grupos sin la incidencia nueva? No:
`duplicate_groups` llama primero a `ensure_index()`, que calcula los embeddings pendientes antes de
comparar. Por eso basta con invalidar al crear.

### 3.5 Cambio: los logs de la caché en la consola — `services/api/main.py`

En la Fase 1 el handler de consola se puso en el logger `api.timing`. Lo moví al logger padre `api`:
en Python, los loggers forman un árbol por los puntos del nombre, y `api.timing` y `api.cache` envían
sus mensajes a `api`. Un solo handler sirve para los dos. En la consola se ve así:

```
INFO:     [api.cache] MISS /api/incidents/duplicates
INFO:     [api.timing] GET /api/incidents/duplicates → 200 | 218.0ms
INFO:     [api.cache] HIT /api/incidents/duplicates
INFO:     [api.timing] GET /api/incidents/duplicates → 200 | 8.0ms
```

### 3.6 Cambio: tests — `tests/cache/`, `tests/inventory/`, `tests/incidents/`, `tests/conftest.py`

**`tests/conftest.py` (modificado)**: la caché vive en la memoria del proceso, y pytest ejecuta todos
los tests en el mismo proceso. Sin vaciarla, un test que cachea el catálogo de **su** base de datos de
pruebas se lo serviría al siguiente test, que tiene otra. Añadí `response_cache.clear()` antes y
después de cada test en la fixture automática que ya existía (`isolated_api`).

**`tests/cache/test_response_cache.py` (nuevo, 12 tests)**: el módulo solo, sin HTTP.
- Primera lectura MISS, segunda HIT (y los logs dicen exactamente eso).
- Caduca justo al llegar al TTL (a los 59,9 s sigue; a los 60 s, no).
- TTL 0 o negativo → error. Una lista vacía también se cachea. Un error no se cachea.
- `invalidate` borra solo esa clave; `invalidate_prefix` borra todas las del prefijo y ninguna más.
- Claves: parámetros ordenados y normalizados; parámetros distintos → claves distintas.
- **Usuarios distintos no comparten entrada** cuando la clave lleva `scope`.

**`tests/inventory/test_inventory_cache.py` (nuevo, 10 tests)**: por HTTP, con la base de datos de pruebas.
- La segunda petición no consulta la base de datos (se cuenta cuántas veces se llama a `list_skus`).
- Caducidad con reloj manual.
- Tras una entrada / una salida, el stock nuevo aparece **sin esperar al TTL**. Tras dar de alta un
  producto, aparece en la lista. Una salida **rechazada** no invalida.
- Una respuesta cacheada **sigue exigiendo sesión** (401 sin token).
- Otro operario reutiliza la entrada: es correcto porque el dato es el mismo para todos.
- El histórico se cachea hasta su TTL y una salida nueva aparece al momento.

**`tests/incidents/test_incident_duplicates_cache.py` (nuevo, 5 tests)**: HIT/MISS, caducidad, crear una
incidencia y resolver otra invalidan, y un 503 (embeddings caídos) no se cachea.

**¿Cómo sé que los tests de invalidación prueban algo?** Comenté temporalmente las líneas
`response_cache.invalidate...` del código y lancé los tests: **fallaron 5**, justo los de invalidación.
Volví a dejar el código como estaba y pasaron. Un test que no falla cuando rompes lo que prueba no vale.

Suite completa: **800 tests, todos en verde** (773 antes de añadir los 27 de la caché).

---

## 4. Fase 4 · Medir otra vez

Resultados completos en `docs/caching/bench-n1-fix.json` y `docs/caching/bench-con-cache.json`.
La API se reinició antes de medir (caché vacía): la 1ª petición es el MISS, el resto son HIT.

| Endpoint | Con seed, sin caché (mediana) | MISS (1ª petición) | HIT (mediana) |
|---|---:|---:|---:|
| `GET /inventory/products` | 380,3 ms | 442,1 ms | **10,5 ms** |
| `GET /api/incidents/duplicates` | 235,3 ms | 219,4 ms | **9,0 ms** |
| `GET /inventory/orders` | 42.557 ms | 2.134 ms | **118,4 ms** |

Cómo leerlo:
- **El MISS cuesta lo mismo que antes** (o algo más: el primer acceso de la mañana a Supabase siempre es
  más lento). La caché no hace más rápido el cálculo; hace que casi nunca haya que hacerlo.
- **El HIT de productos y duplicados (~10 ms)** es casi todo autenticación: buscar el usuario en TinyDB
  (los ~20 ms de `/auth/me` del apartado 1.6) más convertir a JSON.
- **El HIT del histórico sigue en 118 ms** porque, aunque los datos ya están en memoria, FastAPI tiene
  que convertir 22.474 movimientos a 7 MB de JSON y mandarlos. Eso solo se arregla **paginando** (pedir
  100 movimientos cada vez), que cambia el contrato con el frontend y queda fuera de esta tarea.
- **El resto de endpoints no cambió** (mismas cifras que en 1.6, dentro del ruido): no se tocaron.

El informe técnico con todas las decisiones y sus intercambios está en **`CACHING_REPORT.md`**.

---

## 5. Resumen: todos los cambios y por qué

| Archivo | Tipo | Qué y por qué |
|---|---|---|
| `services/api/main.py` | modificado | Middleware de timing (medir cada petición) y handler de consola en el logger `api`, para ver tiempos y HIT/MISS/INVALIDATE |
| `services/seed_perf.py` | nuevo | Seeder de volumen reproducible y reversible (`--purge`), para medir con datos realistas |
| `scripts/bench_api.py` | nuevo | Benchmark repetible: MISS (1ª), mediana y p95 de cada endpoint de lectura |
| `docs/caching/bench-*.json` | nuevos | Resultados: antes del seed, con seed, tras el N+1 y con caché |
| `services/inventory_service.py` | modificado | `selectinload` en `list_orders`: elimina el N+1 (761 → 6 consultas, 42,5 s → 2,1 s) |
| `services/api/cache.py` | nuevo | Caché en memoria con TTL obligatorio, lock, invalidación por clave y prefijo, claves normalizadas y logs |
| `services/routers/inventory.py` | modificado | Caché de productos (60 s) e histórico (120 s); invalidación en las tres escrituras |
| `services/api/routes/incidents.py` | modificado | Caché de duplicados (300 s); invalidación al crear y al cambiar estado |
| `tests/conftest.py` | modificado | Vaciar la caché entre tests |
| `tests/cache/test_response_cache.py` | nuevo | Tests del módulo de caché |
| `tests/inventory/test_inventory_cache.py` | nuevo | Tests HTTP de la caché del inventario |
| `tests/incidents/test_incident_duplicates_cache.py` | nuevo | Tests de la caché de duplicados |
| `uis/backoffice/app/ui/inventory-ui.tsx` | modificado | `useMemo` en `SkuOptions` |
| `uis/backoffice/app/ui/candidate-create-form.tsx` | nuevo | Formulario de alta extraído para cargarlo con `next/dynamic` |
| `uis/backoffice/app/ui/profile-edit-form.tsx` | nuevo | Formulario de edición extraído para cargarlo con `next/dynamic` |
| `uis/backoffice/app/ui/form-skeleton.tsx` | nuevo | `loading` de los formularios diferidos, con las medidas del diseño |
| `uis/backoffice/app/ui/home-client.tsx` | modificado | Carga diferida del formulario de alta |
| `uis/backoffice/app/(protected)/talent/records/[id]/record-detail-client.tsx` | modificado | Carga diferida del formulario de edición |
| `CACHING_REPORT.md` | nuevo | Informe técnico |
| `hito_13.md` | nuevo | Este documento |

### 5.1 Lo que deberías poder explicar después de leer esto

1. Por qué **se mide antes** de optimizar (el N+1 no se habría visto con 6 SKUs; los formularios lazy
   resultaron pesar más, no menos).
2. Por qué **una caché no arregla código lento**: se arregla primero (N+1) y se cachea después.
3. Los tres criterios para cachear (coste × frecuencia × estabilidad) y por qué `/suppliers` o
   `search` no los cumplen.
4. Qué es un **TTL**, por qué es obligatorio, y por qué **invalidar** al escribir hace que el TTL solo
   importe para los cambios que no pasan por la API.
5. Por qué una clave sin el id del usuario es una **fuga de datos** cuando la respuesta es personal, y
   por qué aquí no lo es.
6. Por qué hace falta un **lock** con rutas síncronas, y por qué el cálculo va fuera de él.
7. Por qué esta caché **no sirve con varios workers** y cuándo merecería la pena Redis (`CACHING_REPORT.md`).


