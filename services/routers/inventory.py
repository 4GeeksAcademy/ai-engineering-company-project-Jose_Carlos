"""Inventario (CONTEXT-9): SKUs y movimientos de stock en Supabase, bajo /inventory.

- Todos los datos de negocio van a Supabase con la sesión por petición de `get_db`.
- La autenticación sigue en TinyDB: `get_current_user` valida el JWT contra los usuarios de
  TinyDB, y su `id` es el `user_uuid` que se guarda en cada movimiento.
- Todas las rutas exigen sesión, también las de lectura, como el resto del backoffice: el
  stock de las marcas cliente es información contractual.
- No hay ninguna ruta para modificar o borrar un SKU ni un movimiento: el stock solo cambia
  registrando entradas y salidas.
- Umbrales (/inventory/thresholds) y conteos (/inventory/counts) existen para la telemetría
  (TELEMETRY_PLAN.md PR-1 y PR-2): ninguno de los dos cambia el stock.
- Las respuestas son siempre schemas de services/schemas.py, nunca objetos ORM.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from services import inventory_service
from services.api.cache import make_key, response_cache
from services.api.security import get_current_user
from services.database import get_db
from services.models import StockExit
from services.schemas import (
    SKUCreate,
    SKURead,
    StockCountCreate,
    StockCountRead,
    StockEntryCreate,
    StockEntryCreated,
    StockEntryListItem,
    StockEntryRead,
    StockExitCreate,
    StockExitCreated,
    StockExitListItem,
    StockExitRead,
    StockOrderListItem,
    StockThresholdRead,
    StockThresholdSet,
)


router = APIRouter(prefix="/inventory", tags=["inventory"], dependencies=[Depends(get_current_user)])


# =========================================================
# CACHÉ (services/api/cache.py)
# =========================================================

# Catálogo con el stock calculado de cada SKU: ~380 ms con 759 SKUs (dos SUM agrupados sobre
# 22.000 movimientos en Supabase), y lo piden la lista de productos y los formularios de
# entrada y salida cada vez que se abren. 60 s: el operario ve su propio movimiento al
# instante (las escrituras de abajo invalidan), y el de otro compañero tarda como mucho un
# minuto en aparecer. La salida vuelve a comprobar el stock real en la base de datos con la
# fila bloqueada, así que un dato cacheado nunca permite dejar el stock en negativo.
INVENTORY_PRODUCTS_TTL_SECONDS = 60
INVENTORY_PRODUCTS_CACHE_KEY = make_key("/inventory/products")

# Histórico de movimientos: ~2,1 s con 22.500 movimientos incluso tras quitar el N+1 (1,7 s
# trayendo las filas de Supabase y 0,3 s convirtiéndolas a schemas). Se cachean ya
# convertidos. 120 s: es una consulta de histórico, no de stock disponible, y las entradas
# y salidas registradas desde la API la invalidan al momento. El arreglo de fondo (paginar
# una respuesta de 7 MB) cambia el contrato con el frontend y queda fuera de esta tarea.
INVENTORY_ORDERS_TTL_SECONDS = 120
INVENTORY_ORDERS_CACHE_KEY = make_key("/inventory/orders")

# Todas las respuestas de inventario dependen de los SKUs y los movimientos: cualquier
# escritura borra las cacheadas bajo /inventory. Las mismas para todos los usuarios con
# sesión (el inventario no depende de quién lo consulta), por eso la clave no lleva usuario.
INVENTORY_CACHE_PREFIX = "/inventory/"


def _not_found(error: inventory_service.SKUNotFound) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))


def _order_list_item(order) -> StockEntryListItem | StockExitListItem:
    schema = StockExitListItem if isinstance(order, StockExit) else StockEntryListItem
    return schema.model_validate(order)


# =========================================================
# SKUs
# =========================================================


@router.get("/products", response_model=list[SKURead])
def list_products(db: Session = Depends(get_db)) -> list[SKURead]:
    return response_cache.get_or_set(
        INVENTORY_PRODUCTS_CACHE_KEY, INVENTORY_PRODUCTS_TTL_SECONDS, lambda: inventory_service.list_skus(db)
    )


@router.post("/products", response_model=SKURead, status_code=status.HTTP_201_CREATED)
def create_product(body: SKUCreate, db: Session = Depends(get_db)) -> SKURead:
    try:
        sku = inventory_service.create_sku(db, body)
    except IntegrityError:
        # Otro alta con el mismo código se ha guardado entre la comprobación y el commit.
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"A SKU with code '{body.sku}' already exists")
    except inventory_service.SKUAlreadyExists as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))
    response_cache.invalidate_prefix(INVENTORY_CACHE_PREFIX)
    return inventory_service.to_sku_read(sku, {})


@router.get("/products/{sku_id}", response_model=SKURead)
def get_product(sku_id: int, db: Session = Depends(get_db)) -> SKURead:
    try:
        return inventory_service.get_sku_read(db, sku_id)
    except inventory_service.SKUNotFound as error:
        raise _not_found(error)


# =========================================================
# MOVIMIENTOS DE STOCK
# =========================================================


@router.post("/orders/inbound", response_model=StockEntryCreated, status_code=status.HTTP_201_CREATED)
def register_inbound(
    body: StockEntryCreate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StockEntryCreated:
    try:
        entry = inventory_service.register_entry(db, body, user_uuid=current_user["id"])
    except inventory_service.SKUNotFound as error:
        raise _not_found(error)
    response_cache.invalidate_prefix(INVENTORY_CACHE_PREFIX)
    stock_after = inventory_service.available_stock(db, entry.sku_id, entry.warehouse)
    return StockEntryCreated(**StockEntryRead.model_validate(entry).model_dump(), stock_after=stock_after)


@router.post("/orders/outbound", response_model=StockExitCreated, status_code=status.HTTP_201_CREATED)
def register_outbound(
    body: StockExitCreate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StockExitCreated:
    try:
        stock_exit = inventory_service.register_exit(db, body, user_uuid=current_user["id"])
    except inventory_service.SKUNotFound as error:
        raise _not_found(error)
    except inventory_service.InsufficientStock as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error))
    response_cache.invalidate_prefix(INVENTORY_CACHE_PREFIX)
    stock_after = inventory_service.available_stock(db, stock_exit.sku_id, stock_exit.warehouse)
    return StockExitCreated(**StockExitRead.model_validate(stock_exit).model_dump(), stock_after=stock_after)


@router.get("/orders", response_model=list[StockOrderListItem])
def list_orders(db: Session = Depends(get_db)) -> list[StockEntryListItem | StockExitListItem]:
    return response_cache.get_or_set(
        INVENTORY_ORDERS_CACHE_KEY,
        INVENTORY_ORDERS_TTL_SECONDS,
        lambda: [_order_list_item(order) for order in inventory_service.list_orders(db)],
    )


# =========================================================
# UMBRALES Y CONTEOS (telemetría: PR-1 y PR-2)
# =========================================================

# Fijar un mínimo cambia a quién se avisa y cuándo: solo responsables, no cualquier operario.
THRESHOLD_ROLES = {"admin", "manager"}


@router.get("/thresholds", response_model=list[StockThresholdRead])
def list_thresholds(db: Session = Depends(get_db)) -> list[StockThresholdRead]:
    return [StockThresholdRead.model_validate(threshold) for threshold in inventory_service.list_thresholds(db)]


@router.post("/thresholds", response_model=StockThresholdRead)
def set_threshold(
    body: StockThresholdSet,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StockThresholdRead:
    if current_user["role"] not in THRESHOLD_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only admins and managers can set stock thresholds")
    try:
        threshold = inventory_service.set_threshold(db, body, user_uuid=current_user["id"])
    except inventory_service.SKUNotFound as error:
        raise _not_found(error)
    return StockThresholdRead.model_validate(threshold)


@router.get("/counts", response_model=list[StockCountRead])
def list_counts(db: Session = Depends(get_db)) -> list[StockCountRead]:
    return [StockCountRead.model_validate(count) for count in inventory_service.list_counts(db)]


# Un conteo no mueve stock, así que no invalida la caché de productos ni de movimientos.
@router.post("/counts", response_model=StockCountRead, status_code=status.HTTP_201_CREATED)
def register_count(
    body: StockCountCreate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StockCountRead:
    try:
        count = inventory_service.register_count(db, body, user_uuid=current_user["id"])
    except inventory_service.SKUNotFound as error:
        raise _not_found(error)
    return StockCountRead.model_validate(count)
