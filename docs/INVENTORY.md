# Inventario — doble base de datos (CONTEXT-9, TRK-0341)

API de inventario unificada para los almacenes de Los Ángeles (`LA`) y Zaragoza (`ZGZ`).

| Base de datos | Qué guarda | Dónde se abre | Quién la usa |
| --- | --- | --- | --- |
| TinyDB (`services/api/db.json`) | Usuarios, perfiles, autenticación (y proveedores e incidencias) | `services/database.py` → `tinydb` | `services/api/store.py`, `user_service.py` |
| Supabase (PostgreSQL) | `sku`, `stock_entry`, `stock_exit` | `services/database.py` → `engine`, `get_db` | `services/routers/inventory.py` |

Cada movimiento guarda en `user_uuid` el id del usuario de TinyDB que lo registró. No hay
tabla de usuarios en Supabase.

## Puesta en marcha

1. **Cadena de conexión en `.env`** (nunca en el código; `.env` está en `.gitignore`):

   ```env
   DATABASE_URL=postgresql://postgres.<project-ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres
   ```

   Se copia de Supabase → **Connect** → **Session pooler**. Es la cadena con la contraseña de
   la base de datos: `NEXT_PUBLIC_SUPABASE_URL` y la clave publishable sirven para la API
   REST de Supabase, no para conectar SQLModel. Si la contraseña lleva `@ : / # ?`, escríbelos
   codificados (`%40`, `%3A`…). La conexión directa (`db.<ref>.supabase.co`) solo funciona con
   IPv6; el *session pooler* funciona también con IPv4.

2. **Arrancar la API** — al iniciar se crean en Supabase las tablas que falten y se activa
   RLS en ellas:

   ```bash
   uv run uvicorn services.api.main:app --reload
   ```

3. **Sembrar los datos de CONTEXT-9** — necesita un admin en TinyDB, al que se atribuyen los
   movimientos (o `--user-email` con otro usuario):

   ```bash
   uv run python -m services.api.create_admin admin@trackflow.com 'una-contraseña-larga'
   uv run python -m services.seed_inventory
   ```

   Se puede ejecutar varias veces: no duplica SKUs ni movimientos.

## Endpoints

Todas las rutas exigen `Authorization: Bearer <token>` (el JWT de `/auth/login`), también
las de lectura, igual que el resto del backoffice.

| Método | Ruta | Descripción |
| --- | --- | --- |
| `GET` | `/inventory/products` | SKUs con su stock |
| `POST` | `/inventory/products` | Registra un SKU (empieza con stock 0) |
| `GET` | `/inventory/products/{id}` | Un SKU con su stock |
| `POST` | `/inventory/orders/inbound` | Recepción de mercancía (`StockEntry`) |
| `POST` | `/inventory/orders/outbound` | Despacho o pérdida (`StockExit`) |
| `GET` | `/inventory/orders` | Todos los movimientos, los más recientes primero, con los datos del SKU |

Respuestas de error:

| Caso | Código |
| --- | --- |
| Salida que dejaría el stock del almacén en negativo | `400` — `Insufficient stock for SKU '{sku}'. Available: {available}, requested: {quantity}.` |
| `dispatch` sin `tracking_number`, o `loss` con él | `422` |
| Enviar `current_stock`, `user_uuid`, `created_at` o cualquier campo extra | `422` |
| SKU inexistente | `404` |
| Código de SKU repetido | `409` |
| Sin token o token no válido | `401` |
| Supabase no responde | `503` |

## Decisiones

- **Stock por almacén (regla 6).** `current_stock` es el stock del SKU en **su** almacén
  (`warehouse`); nunca la suma de los dos. Además, `stock_by_warehouse` da el desglose
  `{"LA": n, "ZGZ": m}` por si el SKU tiene movimientos en el otro almacén. Una salida solo
  puede descontar del stock del almacén indicado en la propia salida.
- **El stock no se guarda.** Ni la tabla `sku` tiene columna de stock ni hay rutas para editar
  o borrar SKUs o movimientos. `current_stock = SUMA(entradas) − SUMA(salidas)` por SKU y
  almacén, en dos consultas agregadas.
- **Sin stock negativo, también con peticiones simultáneas.** Una salida bloquea la fila del
  SKU (`SELECT … FOR UPDATE`) hasta su commit, así que dos salidas del mismo SKU se comprueban
  una detrás de otra. Si no hay stock, se rechaza antes de escribir.
- **La base de datos también aplica las reglas.** FK de `stock_entry.sku_id` y
  `stock_exit.sku_id` a `sku.id` (`ON DELETE RESTRICT`), `CHECK` de cantidades positivas,
  almacenes, categorías, tipo de salida y número de seguimiento, y código de SKU único.
- **RLS en Supabase.** Supabase expone el esquema `public` en su API REST con la clave
  publishable. Con RLS activado y sin políticas, esa vía queda cerrada: solo la API de
  FastAPI, que conecta como propietaria de las tablas, puede leer y escribir.
- **ORM y schemas separados.** `services/models.py` (tablas SQLModel) y `services/schemas.py`
  (contrato Pydantic). Los endpoints devuelven siempre schemas.
- **Estructura.** Los archivos siguen CONTEXT-9 (`services/database.py`, `models.py`,
  `schemas.py`, `routers/inventory.py`). La lógica de stock está en
  `services/inventory_service.py`, compartida por el router y el seed. La aplicación sigue en
  `services/api/main.py`, que registra el router.

## Stock tras el seed

| SKU | Almacén | `current_stock` | `stock_by_warehouse` |
| --- | --- | --- | --- |
| CLT-SNK-W-42 | LA | 170 | LA 170 · ZGZ 0 |
| CLT-SNK-W-42-Z | ZGZ | 59 | LA 0 · ZGZ 59 |
| TEC-EAR-001 | LA | 48 | LA 48 · ZGZ 15 |
| CSM-SRM-030 | ZGZ | 155 | LA 0 · ZGZ 155 |
| CLT-CHN-N-32 | LA | 40 | LA 40 · ZGZ 0 |
| TEC-CHG-065 | ZGZ | 75 | LA 0 · ZGZ 75 |
