"""Reglas de negocio del inventario (CONTEXT-9).

- El stock nunca se guarda: para cada SKU y almacén es SUMA(entradas) − SUMA(salidas).
- La única forma de cambiarlo es registrar un movimiento (entrada o salida), y cada
  movimiento guarda el `user_uuid` de TinyDB de quien lo registró.
- Una salida que dejaría el stock del almacén por debajo de cero se rechaza antes de
  escribir nada.

Lo usan el router (services/routers/inventory.py) y el seed (services/seed_inventory.py).
"""

from sqlalchemy import func
from sqlalchemy.orm import selectinload
from sqlmodel import Session, select

from services.models import SKU, WAREHOUSES, StockEntry, StockExit
from services.schemas import SKURead, StockEntryCreate, StockExitCreate


class SKUNotFound(Exception):
    def __init__(self, sku_id: int):
        super().__init__(f"SKU {sku_id} not found")
        self.sku_id = sku_id


class SKUAlreadyExists(Exception):
    def __init__(self, sku: str):
        super().__init__(f"A SKU with code '{sku}' already exists")
        self.sku = sku


class InsufficientStock(Exception):
    def __init__(self, sku: str, available: int, requested: int):
        # Mensaje exacto de CONTEXT-9, regla 2.
        super().__init__(f"Insufficient stock for SKU '{sku}'. Available: {available}, requested: {requested}.")
        self.sku = sku
        self.available = available
        self.requested = requested


# =========================================================
# STOCK (siempre calculado)
# =========================================================


def _totals(db: Session, model, sku_ids: list[int] | None) -> dict[tuple[int, str], int]:
    query = select(model.sku_id, model.warehouse, func.sum(model.quantity)).group_by(model.sku_id, model.warehouse)
    if sku_ids is not None:
        query = query.where(model.sku_id.in_(sku_ids))
    return {(sku_id, warehouse): int(total) for sku_id, warehouse, total in db.exec(query)}


def stock_levels(db: Session, sku_ids: list[int] | None = None) -> dict[int, dict[str, int]]:
    """{sku_id: {"LA": stock, "ZGZ": stock}}: entradas − salidas de cada SKU en cada almacén.

    Dos consultas agregadas en total, sea cual sea el número de SKUs.
    """
    entries = _totals(db, StockEntry, sku_ids)
    exits = _totals(db, StockExit, sku_ids)

    levels: dict[int, dict[str, int]] = {}
    for sku_id, warehouse in entries.keys() | exits.keys():
        by_warehouse = levels.setdefault(sku_id, dict.fromkeys(WAREHOUSES, 0))
        by_warehouse[warehouse] = entries.get((sku_id, warehouse), 0) - exits.get((sku_id, warehouse), 0)
    return levels


def available_stock(db: Session, sku_id: int, warehouse: str) -> int:
    """Stock de un SKU en un almacén concreto."""
    return stock_levels(db, [sku_id]).get(sku_id, {}).get(warehouse, 0)


def to_sku_read(sku: SKU, levels: dict[int, dict[str, int]]) -> SKURead:
    by_warehouse = levels.get(sku.id, dict.fromkeys(WAREHOUSES, 0))
    return SKURead(
        id=sku.id,
        name=sku.name,
        sku=sku.sku,
        client_name=sku.client_name,
        category=sku.category,
        warehouse=sku.warehouse,
        current_stock=by_warehouse[sku.warehouse],
        stock_by_warehouse=by_warehouse,
    )


# =========================================================
# SKUs
# =========================================================


def list_skus(db: Session) -> list[SKURead]:
    skus = db.exec(select(SKU).order_by(SKU.id)).all()
    levels = stock_levels(db)
    return [to_sku_read(sku, levels) for sku in skus]


def get_sku(db: Session, sku_id: int, lock: bool = False) -> SKU:
    query = select(SKU).where(SKU.id == sku_id)
    if lock:
        # Bloquea la fila del SKU hasta el commit: dos salidas simultáneas del mismo SKU se
        # comprueban una detrás de otra y no pueden dejar juntas el stock en negativo.
        query = query.with_for_update()
    sku = db.exec(query).first()
    if sku is None:
        raise SKUNotFound(sku_id)
    return sku


def get_sku_read(db: Session, sku_id: int) -> SKURead:
    sku = get_sku(db, sku_id)
    return to_sku_read(sku, stock_levels(db, [sku.id]))


def create_sku(db: Session, data) -> SKU:
    """Registra un SKU. Empieza siempre con stock 0: solo las entradas le suman unidades."""
    if db.exec(select(SKU.id).where(SKU.sku == data.sku)).first() is not None:
        raise SKUAlreadyExists(data.sku)
    sku = SKU(**data.model_dump())
    db.add(sku)
    db.commit()
    db.refresh(sku)
    return sku


# =========================================================
# MOVIMIENTOS
# =========================================================


def register_entry(db: Session, data: StockEntryCreate, user_uuid: str) -> StockEntry:
    get_sku(db, data.sku_id)
    entry = StockEntry(**data.model_dump(), user_uuid=user_uuid)
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def register_exit(db: Session, data: StockExitCreate, user_uuid: str) -> StockExit:
    sku = get_sku(db, data.sku_id, lock=True)
    available = available_stock(db, sku.id, data.warehouse)
    if data.quantity > available:
        code = sku.sku  # antes del rollback, que expira el objeto
        # Nada se ha escrito todavía: se suelta el bloqueo y se rechaza.
        db.rollback()
        raise InsufficientStock(code, available, data.quantity)

    stock_exit = StockExit(**data.model_dump(), user_uuid=user_uuid)
    db.add(stock_exit)
    db.commit()
    db.refresh(stock_exit)
    return stock_exit


def list_orders(db: Session) -> list[StockEntry | StockExit]:
    """Entradas y salidas juntas, las más recientes primero."""
    # selectinload trae los SKU de todos los movimientos en una sola consulta extra
    # (WHERE id IN (...)). Sin él, cada `order.sku` que lee el router lanzaba su propia
    # consulta: 2 + N consultas, ~760 con el seed de rendimiento (el problema N+1).
    entries = db.exec(select(StockEntry).options(selectinload(StockEntry.sku))).all()
    exits = db.exec(select(StockExit).options(selectinload(StockExit.sku))).all()
    # Mismo instante: la salida va antes que la entrada (es la que tuvo que comprobar el stock).
    return sorted(
        [*entries, *exits],
        key=lambda order: (order.created_at, isinstance(order, StockExit), order.id),
        reverse=True,
    )
