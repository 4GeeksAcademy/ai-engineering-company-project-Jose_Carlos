"""Reglas de negocio del inventario (CONTEXT-9).

- El stock nunca se guarda: para cada SKU y almacén es SUMA(entradas) − SUMA(salidas).
- La única forma de cambiarlo es registrar un movimiento (entrada o salida), y cada
  movimiento guarda el `user_uuid` de TinyDB de quien lo registró.
- Una salida que dejaría el stock del almacén por debajo de cero se rechaza antes de
  escribir nada.
- Telemetría (TELEMETRY_PLAN.md): una salida que cruza hacia abajo el stock mínimo emite
  `stock_threshold_triggered`, y un conteo que no cuadra emite
  `inventory_discrepancy_detected`. Los dos se emiten aquí, después del commit, porque solo
  el servidor ve el cruce y la diferencia, salga el movimiento del backoffice, de la API o del seed.

Lo usan el router (services/routers/inventory.py) y el seed (services/seed_inventory.py).
"""

from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import selectinload
from sqlmodel import Session, select

from services import telemetry
from services.models import SKU, WAREHOUSES, StockCount, StockEntry, StockExit, StockThreshold
from services.schemas import SKURead, StockCountCreate, StockEntryCreate, StockExitCreate, StockThresholdSet


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

    min_stock = threshold_for(db, sku.id, data.warehouse)
    stock_exit = StockExit(**data.model_dump(), user_uuid=user_uuid)
    db.add(stock_exit)
    db.commit()
    db.refresh(stock_exit)

    stock_after = available - data.quantity
    # Disparo por flanco: solo la salida que CRUZA el mínimo. Mientras el stock siga por
    # debajo no se repite; una entrada que lo devuelva a >= min_stock lo rearma. El bloqueo
    # de la fila del SKU serializa las salidas, así que dos no pueden cruzarlo a la vez.
    if min_stock is not None and available >= min_stock > stock_after:
        telemetry.emit(
            "stock_threshold_triggered",
            {
                **telemetry.inventory_properties(stock_exit.sku, data.warehouse, stock_after),
                "min_stock": min_stock,
                "stock_before": available,
                "trigger_order_type": data.exit_type,
                "trigger_order_id": stock_exit.id,
            },
            user_id=user_uuid,
        )
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


# =========================================================
# UMBRALES DE STOCK MÍNIMO (PR-1)
# =========================================================


def threshold_for(db: Session, sku_id: int, warehouse: str) -> int | None:
    """Stock mínimo configurado para un SKU en un almacén, o None si no tiene."""
    return db.exec(
        select(StockThreshold.min_stock).where(StockThreshold.sku_id == sku_id, StockThreshold.warehouse == warehouse)
    ).first()


def set_threshold(db: Session, data: StockThresholdSet, user_uuid: str) -> StockThreshold:
    """Fija el mínimo de un SKU en un almacén; si ya tenía uno, lo sustituye."""
    get_sku(db, data.sku_id)
    threshold = db.exec(
        select(StockThreshold).where(StockThreshold.sku_id == data.sku_id, StockThreshold.warehouse == data.warehouse)
    ).first()
    if threshold is None:
        threshold = StockThreshold(**data.model_dump(), user_uuid=user_uuid)
    else:
        threshold.min_stock = data.min_stock
        threshold.user_uuid = user_uuid
        threshold.updated_at = datetime.now(tz=timezone.utc)
    db.add(threshold)
    db.commit()
    db.refresh(threshold)
    return threshold


def list_thresholds(db: Session) -> list[StockThreshold]:
    return db.exec(select(StockThreshold).order_by(StockThreshold.sku_id, StockThreshold.warehouse)).all()


# =========================================================
# CONTEOS FÍSICOS (PR-2)
# =========================================================


def register_count(db: Session, data: StockCountCreate, user_uuid: str) -> StockCount:
    """Registra un conteo físico frente al stock calculado. No corrige el stock: la corrección,
    si procede, sigue siendo una salida `loss` o una entrada, trazables a un usuario."""
    sku = get_sku(db, data.sku_id)
    system_quantity = available_stock(db, sku.id, data.warehouse)
    count = StockCount(**data.model_dump(), system_quantity=system_quantity, user_uuid=user_uuid)
    db.add(count)
    db.commit()
    db.refresh(count)

    difference = count.counted_quantity - system_quantity
    if difference:
        telemetry.emit(
            "inventory_discrepancy_detected",
            {
                **telemetry.inventory_properties(count.sku, data.warehouse, abs(difference)),
                "system_quantity": system_quantity,
                "counted_quantity": count.counted_quantity,
                "difference": difference,
                "count_type": count.count_type,
                "count_id": count.id,
            },
            user_id=user_uuid,
        )
    return count


def list_counts(db: Session) -> list[StockCount]:
    """Conteos, los más recientes primero."""
    counts = db.exec(select(StockCount).options(selectinload(StockCount.sku))).all()
    return sorted(counts, key=lambda count: (count.created_at, count.id), reverse=True)
