"""Inventario (CONTEXT-9): SKUs y movimientos de stock en Supabase, bajo /inventory.

- Todos los datos de negocio van a Supabase con la sesión por petición de `get_db`.
- La autenticación sigue en TinyDB: `get_current_user` valida el JWT contra los usuarios de
  TinyDB, y su `id` es el `user_uuid` que se guarda en cada movimiento.
- Todas las rutas exigen sesión, también las de lectura, como el resto del backoffice: el
  stock de las marcas cliente es información contractual.
- No hay ninguna ruta para modificar o borrar un SKU ni un movimiento: el stock solo cambia
  registrando entradas y salidas.
- Las respuestas son siempre schemas de services/schemas.py, nunca objetos ORM.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from services import inventory_service
from services.api.security import get_current_user
from services.database import get_db
from services.models import StockExit
from services.schemas import (
    SKUCreate,
    SKURead,
    StockEntryCreate,
    StockEntryRead,
    StockExitCreate,
    StockExitRead,
    StockOrderRead,
)


router = APIRouter(prefix="/inventory", tags=["inventory"], dependencies=[Depends(get_current_user)])


def _not_found(error: inventory_service.SKUNotFound) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))


def _order_read(order) -> StockEntryRead | StockExitRead:
    schema = StockExitRead if isinstance(order, StockExit) else StockEntryRead
    return schema.model_validate(order)


# =========================================================
# SKUs
# =========================================================


@router.get("/products", response_model=list[SKURead])
def list_products(db: Session = Depends(get_db)) -> list[SKURead]:
    return inventory_service.list_skus(db)


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


@router.post("/orders/inbound", response_model=StockEntryRead, status_code=status.HTTP_201_CREATED)
def register_inbound(
    body: StockEntryCreate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StockEntryRead:
    try:
        entry = inventory_service.register_entry(db, body, user_uuid=current_user["id"])
    except inventory_service.SKUNotFound as error:
        raise _not_found(error)
    return StockEntryRead.model_validate(entry)


@router.post("/orders/outbound", response_model=StockExitRead, status_code=status.HTTP_201_CREATED)
def register_outbound(
    body: StockExitCreate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StockExitRead:
    try:
        stock_exit = inventory_service.register_exit(db, body, user_uuid=current_user["id"])
    except inventory_service.SKUNotFound as error:
        raise _not_found(error)
    except inventory_service.InsufficientStock as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error))
    return StockExitRead.model_validate(stock_exit)


@router.get("/orders", response_model=list[StockOrderRead])
def list_orders(db: Session = Depends(get_db)) -> list[StockEntryRead | StockExitRead]:
    return [_order_read(order) for order in inventory_service.list_orders(db)]
