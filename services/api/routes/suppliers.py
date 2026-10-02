from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status

from services.api import store
from services.api.models import (
    RateUpdate,
    StatusUpdate,
    SupplierCategory,
    SupplierCreate,
    SupplierResponse,
)
from services.api.security import get_current_user


# El prefijo /suppliers se añade en main.py con app.include_router(...)
# Todas las rutas de proveedores (tarifas, estados, contactos) requieren un JWT válido.
router = APIRouter(tags=["suppliers"], dependencies=[Depends(get_current_user)])


def _now_utc() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _not_found(supplier_id: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Supplier {supplier_id} not found",
    )


# =========================================================
# ENDPOINTS
# =========================================================


@router.post("", response_model=SupplierResponse, status_code=status.HTTP_201_CREATED)
def create_supplier(supplier: SupplierCreate):
    # Pydantic ya ha validado el cuerpo (422 si falla) antes de llegar aquí.
    # id y updated_at los pone siempre el servidor.
    data = supplier.model_dump(mode="json")
    data["updated_at"] = _now_utc()
    return store.create_supplier(data)


@router.get("", response_model=list[SupplierResponse])
def list_suppliers(
    country: Literal["USA", "Spain"] | None = None,
    category: SupplierCategory | None = None,
):
    # Los filtros se combinan con AND
    suppliers = store.get_all_suppliers()
    if country is not None:
        suppliers = [s for s in suppliers if s["country"] == country]
    if category is not None:
        suppliers = [s for s in suppliers if category.value in s["categories"]]
    return suppliers


@router.get("/{supplier_id}", response_model=SupplierResponse)
def get_supplier(supplier_id: int):
    supplier = store.get_supplier_by_id(supplier_id)
    if supplier is None:
        raise _not_found(supplier_id)
    return supplier


@router.patch("/{supplier_id}/rate", response_model=SupplierResponse)
def update_rate(supplier_id: int, body: RateUpdate):
    # Trazabilidad de tarifas: cada cambio de tarifa actualiza updated_at
    supplier = store.update_supplier(
        supplier_id,
        {"rate_per_shipment": body.rate_per_shipment, "updated_at": _now_utc()},
    )
    if supplier is None:
        raise _not_found(supplier_id)
    return supplier


@router.patch("/{supplier_id}/status", response_model=SupplierResponse)
def update_status(supplier_id: int, body: StatusUpdate):
    # updated_at es el timestamp de la última actualización de TARIFA (CONTEXT-7),
    # por eso un cambio de estado no lo modifica.
    supplier = store.update_supplier(supplier_id, {"status": body.status.value})
    if supplier is None:
        raise _not_found(supplier_id)
    return supplier


@router.delete("/{supplier_id}", response_model=SupplierResponse)
def delete_supplier(supplier_id: int):
    # Devolvemos 200 con el proveedor tal como estaba antes de borrarlo.
    # En TrackFlow lo habitual es suspender, no borrar.
    supplier = store.delete_supplier(supplier_id)
    if supplier is None:
        raise _not_found(supplier_id)
    return supplier
