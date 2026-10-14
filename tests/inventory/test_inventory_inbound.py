"""POST /inventory/orders/inbound — recepciones de mercancía (StockEntry)."""

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlmodel import select

from services.models import StockEntry
from services.routers.inventory import get_product, register_inbound
from services.schemas import MAX_QUANTITY, StockEntryCreate, StockEntryRead


def _entry(sku, **overrides):
    return StockEntryCreate(**{
        "sku_id": sku.id, "quantity": 120, "reference": "PO-2024-0098", "warehouse": sku.warehouse, **overrides,
    })


# =========================================================
# Camino feliz
# =========================================================


def test_inbound_order_adds_stock_and_is_traceable_to_its_user(db, sneaker, operator):
    entry = register_inbound(_entry(sneaker), current_user=operator, db=db)

    assert isinstance(entry, StockEntryRead)
    assert entry.order_type == "inbound"
    assert (entry.quantity, entry.reference, entry.warehouse) == (120, "PO-2024-0098", "LA")
    assert entry.user_uuid == operator["id"]
    assert entry.created_at is not None
    assert entry.sku.sku == "CLT-SNK-W-42"
    assert get_product(sneaker.id, db=db).current_stock == 120


def test_successive_receptions_accumulate(db, sneaker, operator):
    register_inbound(_entry(sneaker, quantity=120), current_user=operator, db=db)
    register_inbound(_entry(sneaker, quantity=80, reference="GR-LA-0234"), current_user=operator, db=db)

    assert get_product(sneaker.id, db=db).current_stock == 200
    assert len(db.exec(select(StockEntry)).all()) == 2


# =========================================================
# Casos límite
# =========================================================


def test_reception_in_the_other_warehouse_counts_only_there(db, sneaker, operator):
    register_inbound(_entry(sneaker, quantity=15, warehouse="ZGZ"), current_user=operator, db=db)

    product = get_product(sneaker.id, db=db)
    assert product.current_stock == 0
    assert product.stock_by_warehouse == {"LA": 0, "ZGZ": 15}


@pytest.mark.parametrize("quantity", [1, MAX_QUANTITY])
def test_inbound_accepts_quantities_on_the_boundary(db, sneaker, operator, quantity):
    register_inbound(_entry(sneaker, quantity=quantity), current_user=operator, db=db)

    assert get_product(sneaker.id, db=db).current_stock == quantity


def test_each_user_is_recorded_on_their_own_order(db, sneaker, operator):
    other = {"id": "another-tinydb-uuid"}

    first = register_inbound(_entry(sneaker), current_user=operator, db=db)
    second = register_inbound(_entry(sneaker), current_user=other, db=db)

    assert (first.user_uuid, second.user_uuid) == (operator["id"], "another-tinydb-uuid")


# =========================================================
# Modos de fallo
# =========================================================


def test_inbound_for_unknown_sku_is_not_found_and_writes_nothing(db, sneaker, operator):
    with pytest.raises(HTTPException) as error:
        register_inbound(_entry(sneaker, sku_id=sneaker.id + 1000), current_user=operator, db=db)

    assert error.value.status_code == 404
    assert db.exec(select(StockEntry)).all() == []


@pytest.mark.parametrize("overrides", [
    {"quantity": 0},
    {"quantity": -5},
    {"quantity": 2.5},
    {"quantity": "10"},
    {"quantity": True},
    {"quantity": MAX_QUANTITY + 1},
    {"reference": "  "},
    {"warehouse": "MAD"},
    {"sku_id": 0},
    {"user_uuid": "someone-else"},
    {"created_at": "2020-01-01T00:00:00Z"},
])
def test_inbound_rejects_invalid_or_server_side_fields(sneaker, overrides):
    with pytest.raises(ValidationError):
        _entry(sneaker, **overrides)


@pytest.mark.parametrize("missing", ["sku_id", "quantity", "reference", "warehouse"])
def test_inbound_requires_every_field(missing):
    payload = {"sku_id": 1, "quantity": 1, "reference": "PO-1", "warehouse": "LA"}
    del payload[missing]

    with pytest.raises(ValidationError):
        StockEntryCreate(**payload)
