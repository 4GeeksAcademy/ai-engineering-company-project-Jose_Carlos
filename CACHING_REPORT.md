# Informe de caching · TrackFlow

Rama `feature/caching-optimisation`. Explicación paso a paso para aprender: `hito_13.md`.
Datos en bruto: `docs/caching/bench-*.json`.

## 1. Metodología

**Entorno.**
- API en local: uvicorn, 1 worker, como `docker/start-app.sh`.
- Inventario en Supabase (PostgreSQL remoto, ~50 ms por viaje de ida y vuelta).
- Usuarios, proveedores e incidencias en TinyDB (archivo JSON local).
- Frontend: `next build` de Next 16.3.2 con Turbopack.

**Medición.**
- `scripts/bench_api.py` inicia sesión y lanza cada GET de lectura 10 veces seguidas, con la misma URL y los mismos parámetros. Son 19 endpoints.
- Por cada endpoint guarda la 1ª petición aparte (es el MISS cuando hay caché), la mediana del resto (el HIT), el p95 y el tamaño de la respuesta.
- Cada GET de la API escribe su latencia en consola gracias al middleware de `services/api/main.py`.
- La caché escribe `HIT`, `MISS` o `INVALIDATE` en el logger `api.cache`.

**Datos.**
- `services/seed_perf.py` genera un año de actividad 3PL con semilla fija (13), de forma reproducible.
- 36 marcas ficticias en los almacenes LA y ZGZ.
- La demanda es lognormal, con reposición por punto de pedido, mermas y estacionalidad.
- Las incidencias citan SKUs y números de seguimiento que existen en el propio seed.
- Escribe en una sola transacción y comprueba que ningún stock queda negativo antes del commit.
- `--purge` deja los datos como estaban antes del seed.

| Tabla | Antes del seed | Después |
|---|---:|---:|
| `sku` | 6 | 759 |
| `stock_entry` | 8 | 1.451 |
| `stock_exit` | 4 | 21.023 |
| `incidents` (TinyDB) | 95 | 1.295 |
| `incident_embeddings` (TinyDB) | 95 | 1.295 |

**Cómo cambió la latencia con el seed** (mediana, ms):

| Endpoint | Antes del seed | Con seed | Causa |
|---|---:|---:|---|
| `/auth/me`, `/suppliers`, `/api/incidents/summary` | 3–6 | 17–20 | TinyDB relee `db.json` entero en cada operación (53 KB → 717 KB). La autenticación lo paga en todas las rutas |
| `/api/incidents/duplicates`, `search`, `{id}/similar` | 15–26 | 235–248 | Cada llamada relee 5,4 MB de embeddings |
| `/inventory/products` | 280 | 380 | `SUM … GROUP BY` sobre 22.474 movimientos, más 3 viajes a Supabase |
| `/inventory/orders` | 540 | 42.557 | N+1: 761 consultas SQL, una por SKU |

## 2. Decisiones frontend

JS propio de cada ruta en la carga inicial (todas comparten además 461 KB, 138 KB en gzip):

| Cambio | Ruta | Antes | Después | Chunk diferido |
|---|---|---:|---:|---:|
| `next/dynamic` del formulario "Nueva candidatura" | `/talent` | 62,9 KB (21,2 gz) | 65,1 KB (22,3 gz) | 2,9 KB (0,8 gz) |
| `next/dynamic` del formulario "Editar perfil" | `/talent/records/[id]` | 66,9 KB (22,0 gz) | 69,5 KB (23,2 gz) | 2,6 KB (0,8 gz) |
| `useMemo` en `SkuOptions` | `/inventory/orders/inbound` y `/outbound` | 51,1 / 55,5 KB | igual | — |

**Lazy loading.**
- Los dos formularios solo se montan al pulsar un botón, y la mayoría de visitas no lo pulsan.
- El `loading` es `FormSkeleton`: tiene la misma altura, borde y radio que los inputs, así que no hay salto de layout al aparecer el formulario.
- No se usa `ssr: false`. Los formularios no tocan APIs del navegador y empiezan cerrados, así que el servidor nunca los pinta.
- **Resultado medido: la carga inicial crece unos 1,1 KB gzip por ruta.**
  - Turbopack mete en el chunk de cada ruta el código de soporte de `next/dynamic` (`BailoutToCSR`, `PreloadChunks`, el envoltorio de `loading`), unos 5 KB.
  - Eso es más de lo que pesa cada formulario diferido (~2,7 KB).
  - El proyecto no tiene ninguna dependencia pesada que diferir: solo `next`, `react` y `react-dom`.
- Se mantiene porque lo exige la tarea y deja el patrón listo. En un proyecto real no se aplicaría a componentes de este tamaño.

**`useMemo` en `SkuOptions`.**
- Ordenar 759 SKUs con `localeCompare("es")` y crear sus `<option>` costaba ~1,5 ms en cada render. Medido en Node con los datos reales; en equipos lentos, de 2 a 4 veces más.
- Los formularios de entrada y salida se repintan con cada tecla.
- La dependencia `[skus]` es el estado de `useApiResource`, con referencia estable, así que solo se recalcula al recargar el catálogo.

**Verificación.**
- `tsc` sin errores.
- `eslint`: los 2 errores que ya había antes, en líneas no tocadas.
- Jest: 148/148.
- Arnés de UI en Chrome: Talent 37/37 (abre el formulario diferido) e Inventario 40/40.

## 3. Decisiones backend

Módulo `services/api/cache.py`:
- Diccionario `clave → (valor, caducidad)` en memoria.
- TTL obligatorio y mayor que 0.
- `threading.Lock`, porque las rutas `def` corren en el threadpool. El cálculo se hace fuera del lock.
- Reloj monotónico.
- Invalidación por clave y por prefijo.
- Las excepciones no se cachean.
- Las claves se forman con la ruta, los parámetros ordenados y sin vacíos y, si la respuesta es personal, `|scope=<id>`.

| Endpoint | Sin caché (con seed) | MISS | HIT | Frecuencia | TTL | Invalidación |
|---|---:|---:|---:|---|---:|---|
| `GET /inventory/products` | 380 ms | 442 ms | **10,5 ms** | Lo cargan 3 pantallas al abrirse (productos, entrada, salida) y el botón "Actualizar" | 60 s | `POST /inventory/products`, `/orders/inbound`, `/orders/outbound` (prefijo `/inventory/`) |
| `GET /inventory/orders` | 42.557 ms → **2.131 ms** sin caché tras arreglar el N+1 | 2.134 ms | **118 ms** | Pantalla de movimientos al abrirse y "Actualizar" | 120 s | Las mismas tres escrituras |
| `GET /api/incidents/duplicates` | 235 ms | 219 ms | **9,0 ms** | Cada visita a `/incidents`, y se recarga tras cada cambio de estado | 300 s | `POST /api/incidents`, `PATCH /api/incidents/{id}/status` |

Notas sobre los resultados:
- **Orden de trabajo.** Primero se arregló el código: `selectinload` en `inventory_service.list_orders` pasó de 761 a 6 sentencias SQL. Solo después se cacheó. Los 2,1 s que quedaban se repartían en 1,7 s de traer 22.474 filas, 0,3 s de convertir a schemas y 0,07 s de generar el JSON.
- **El HIT de ~10 ms** es casi todo autenticación (leer TinyDB) más serialización.
- **El HIT de orders (118 ms)** es serializar y enviar 7 MB. Lo arregla paginar, no la caché.
- **Las invalidaciones se lanzan después de que la escritura se haya guardado bien.** Una salida rechazada (400), un 404 o un 409 no invalidan.
- **Duplicados tras crear una incidencia.** El embedding de la nueva se calcula en segundo plano, pero `duplicate_groups` indexa los pendientes antes de comparar, así que basta con invalidar al crear.

**Tests.**
- 27 tests nuevos (`tests/cache/`, `tests/inventory/test_inventory_cache.py`, `tests/incidents/test_incident_duplicates_cache.py`). Cubren:
  - MISS en la primera lectura y HIT en la segunda;
  - caducidad exacta con un reloj simulado;
  - que cada escritura invalida y la siguiente lectura trae el dato nuevo;
  - que una escritura rechazada no invalida;
  - que una respuesta cacheada sigue exigiendo sesión;
  - que usuarios con distinto `scope` no comparten entrada;
  - que los errores no se cachean.
- Al comentar las líneas de invalidación, fallan los 5 tests de invalidación.
- Suite completa: 800/800.

## 4. Intercambios reconocidos

**Frescura frente a rendimiento, en este dominio.**
- **Stock.** Es el dato más delicado: un operario de Zaragoza decide si prepara un pedido según el stock que ve.
  - Sus propios movimientos y los de sus compañeros a través de la API se ven al instante, porque invalidan.
  - El TTL solo cubre los cambios que no pasan por la API: el seed, scripts, o un SQL manual en Supabase. Esos tardan como mucho 60 s en verse.
  - Un dato desfasado nunca puede dejar el stock en negativo: `register_exit` bloquea la fila del SKU (`with_for_update`) y recalcula contra la base de datos sin caché. Lo peor que puede pasar es que una salida se rechace con "Insufficient stock" aunque la pantalla mostrara más unidades. Es un error visible, no un dato corrupto.
- **Histórico (120 s).** Es un registro de lo que ya pasó, no una decisión en tiempo real.
- **Duplicados (300 s).** Es un panel de revisión, no una alarma. No retrasa ninguna entrega.
- **El botón "Actualizar".** Ahora devuelve la versión cacheada hasta que caduca el TTL. Para cambios hechos a través de la API da igual, porque invalidan; para cambios externos, el botón ya no fuerza un dato fresco. Si fuera un problema, se puede añadir una cabecera `Cache-Control: no-cache` que salte la caché.

**Límites de una caché en memoria.**
- **Se pierde al reiniciar.** Tras cada despliegue o reinicio, la primera petición de cada endpoint paga el MISS completo: 2,1 s en el histórico.
- **Una caché por worker.** Hoy se arranca con un worker. Con `--workers 4` habría 4 cachés independientes:
  - la memoria se multiplica por 4 (el histórico cacheado ocupa ~38,5 MB y el catálogo ~1,2 MB);
  - habría 4 MISS por cada clave;
  - el peor efecto es la invalidación: una entrada registrada en el worker 1 solo borra la caché del worker 1. Los otros tres seguirían sirviendo el stock anterior hasta su TTL, y un usuario podría ver el dato nuevo y luego el viejo según a qué worker caiga su petición.
- **Las invalidaciones no se propagan** a otras instancias (varios contenedores) ni detectan escrituras hechas fuera de la API.
- **Cache stampede.** Si llegan varias peticiones a la vez con la entrada vacía, todas calculan. Se aceptó para no bloquear el lock durante 2 s.
- **Los valores se comparten por referencia.** Quien los lee no debe modificarlos. Ninguna ruta lo hace hoy.

**Cuándo compensaría Redis.** Cuando haya más de un worker o más de una instancia, porque entonces hace falta una caché y una invalidación compartidas y coherentes. También si los MISS tras cada despliegue empiezan a doler. Con un worker, un despliegue en un solo contenedor y un backoffice interno de pocos usuarios, Redis añadiría un servicio que operar, otra latencia de red y otro punto de fallo, a cambio de nada.

## 5. Qué no se cacheó

**Endpoints.**
- **`GET /api/incidents/search` y `GET /api/incidents/{id}/similar` (~240 ms).** Son caros, pero la clave incluye el texto buscado o el id, y casi cada petición es distinta, así que la tasa de HIT sería muy baja. Su coste está en releer 5,4 MB de embeddings en cada llamada: lo arregla mantener el índice en memoria, no cachear respuestas.
- **`GET /suppliers` y `GET /api/incidents/summary` (17–19 ms).** Su coste es el mismo suelo que la autenticación. Una caché no lo bajaría y añadiría invalidaciones que mantener.
- **`GET /inventory/products/{id}` (~275 ms).** Hay una clave por SKU y cada una se consulta poco; la caché del catálogo ya cubre las pantallas.
- **`GET /api/incidents/semantic-status`.** Sus 3 s iniciales son la carga del modelo de embeddings, una vez por arranque.

**Componentes.**
- **`useMemo` en `ProductsClient` (0,06 ms por render) y en el filtro de `OrdersClient` (0,43 ms sin búsqueda).** Memoizar añadiría dependencias que mantener para ahorrar menos de lo que mide el ruido.
- **`SimilarRow` en incidencias.** Se planteó como alternativa para el lazy loading, pero con el coste fijo medido en la sección 2 ahorraría todavía menos que los formularios.

## 6. Datos privados

- **Ningún endpoint cacheado depende del usuario.** El catálogo, el histórico y los grupos de duplicados son iguales para cualquier empleado con sesión: el backoffice no filtra por usuario ni por marca cliente. Por eso su clave no lleva `scope`, y un test comprueba que un segundo operario recibe la misma entrada.
- **La autenticación va antes que la caché.** Es una dependencia del router, `Depends(get_current_user)`, que FastAPI ejecuta antes de la función. Sin token válido la respuesta es 401 y nunca se llega a leer la caché; un test lo comprueba con una entrada ya cacheada.
- **Se descartaron `/auth/me`, `/users/me` y `/profiles/me`.** Son datos personales. Con la clave equivocada, un usuario recibiría el perfil de otro, y la ganancia (~20 ms) no justifica el riesgo.
- **Si algún día hubiera que cachear algo personal**, `make_key(..., scope=user_id)` pone el id en la clave. Un test comprueba que usuarios distintos no comparten entrada.
- **El histórico cacheado incluye el `user_uuid` de quien registró cada movimiento.** Es el mismo dato que ya devolvía el endpoint a todos los usuarios con sesión; la caché no amplía quién lo ve.
