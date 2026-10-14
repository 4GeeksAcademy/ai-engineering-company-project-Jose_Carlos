"""GET/POST /inventory/products y GET /inventory/products/{id} — SKUs con su stock calculado."""

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlmodel import select

from services.models import SKU
from services.routers.inventory import create_product, get_product, list_products
from services.schemas import SKUCreate, SKURead

SNEAKER = {
    "name": "Zapatilla blanca clásica - Talla 42",
    "sku": "CLT-SNK-W-42",
    "client_name": "PureStep Footwear",
    "category": "fashion",
    "warehouse": "LA",
}


# =========================================================
# POST /inventory/products
# =========================================================


def test_create_product_registers_the_sku_with_zero_stock(db):
    created = create_product(SKUCreate(**SNEAKER), db=db)

    assert isinstance(created, SKURead)
    assert created.model_dump(exclude={"id"}) == {
        **SNEAKER, "current_stock": 0, "stock_by_warehouse": {"LA": 0, "ZGZ": 0},
    }
    assert db.get(SKU, created.id).sku == "CLT-SNK-W-42"


def test_create_product_trims_text_fields(db):
    created = create_product(SKUCreate(**{**SNEAKER, "name": "  Zapatilla  ", "sku": " CLT-1 "}), db=db)

    assert (created.name, created.sku) == ("Zapatilla", "CLT-1")


def test_create_product_with_an_existing_code_is_a_conflict(db, sneaker):
    with pytest.raises(HTTPException) as error:
        create_product(SKUCreate(**{**SNEAKER, "warehouse": "ZGZ"}), db=db)

    assert error.value.status_code == 409
    assert len(db.exec(select(SKU)).all()) == 1


@pytest.mark.parametrize("overrides", [
    {"category": "food"},
    {"warehouse": "MAD"},
    {"warehouse": "la"},
    {"name": "   "},
    {"sku": ""},
    {"client_name": None},
    {"sku": "x" * 65},
])
def test_create_product_rejects_invalid_fields(overrides):
    with pytest.raises(ValidationError):
        SKUCreate(**{**SNEAKER, **overrides})


@pytest.mark.parametrize("missing", ["name", "sku", "client_name", "category", "warehouse"])
def test_create_product_requires_every_field(missing):
    payload = {key: value for key, value in SNEAKER.items() if key != missing}

    with pytest.raises(ValidationError):
        SKUCreate(**payload)


@pytest.mark.parametrize("stock_field", ["current_stock", "stock", "stock_by_warehouse"])
def test_stock_cannot_be_set_when_creating_a_product(stock_field):
    # El stock solo cambia con movimientos: enviarlo es un error, no se ignora en silencio.
    with pytest.raises(ValidationError):
        SKUCreate(**SNEAKER, **{stock_field: 500})


# =========================================================
# GET /inventory/products
# =========================================================


def test_list_products_returns_every_sku_with_its_stock(db, make_sku, receive, dispatch):
    sneaker = make_sku()
    serum = make_sku(name="Sérum facial hidratante 30ml", sku="CSM-SRM-030", client_name="GlowLab Cosmetics",
                     category="cosmetics", warehouse="ZGZ")
    receive(sneaker, 120)
    receive(sneaker, 80, reference="GR-LA-0234")
    dispatch(sneaker, 30)
    receive(serum, 200)

    products = list_products(db=db)

    assert all(isinstance(product, SKURead) for product in products)
    assert [(p.sku, p.current_stock) for p in products] == [("CLT-SNK-W-42", 170), ("CSM-SRM-030", 200)]


def test_list_products_on_empty_inventory_is_empty(db):
    assert list_products(db=db) == []


def test_new_sku_is_listed_with_zero_stock(db, sneaker):
    [product] = list_products(db=db)

    assert product.current_stock == 0
    assert product.stock_by_warehouse == {"LA": 0, "ZGZ": 0}


def test_stock_is_per_warehouse_and_never_added_up(db, sneaker, receive):
    # CONTEXT-9, regla 6: 20 en LA y 15 en ZGZ son dos cifras, no 35.
    receive(sneaker, 20, warehouse="LA")
    receive(sneaker, 15, warehouse="ZGZ")

    [product] = list_products(db=db)

    assert product.current_stock == 20  # el almacén del SKU es LA
    assert product.stock_by_warehouse == {"LA": 20, "ZGZ": 15}


def test_stock_of_one_sku_does_not_leak_into_another(db, make_sku, receive):
    first, second = make_sku(), make_sku(sku="CLT-SNK-W-43")
    receive(first, 10)

    assert [p.current_stock for p in list_products(db=db)] == [10, 0]
    assert second.id != first.id


# =========================================================
# GET /inventory/products/{id}
# =========================================================


def test_get_product_returns_the_sku_with_its_current_stock(db, sneaker, receive, dispatch):
    receive(sneaker, 50)
    dispatch(sneaker, 2, exit_type="loss")

    product = get_product(sneaker.id, db=db)

    assert isinstance(product, SKURead)
    assert (product.sku, product.current_stock) == ("CLT-SNK-W-42", 48)


def test_get_product_reports_the_stock_of_its_own_warehouse(db, make_sku, receive):
    serum = make_sku(sku="CSM-SRM-030", category="cosmetics", warehouse="ZGZ")
    receive(serum, 5, warehouse="LA")
    receive(serum, 9, warehouse="ZGZ")

    product = get_product(serum.id, db=db)

    assert product.current_stock == 9
    assert product.stock_by_warehouse == {"LA": 5, "ZGZ": 9}


@pytest.mark.parametrize("offset", [1000, -1000])
def test_get_unknown_product_is_not_found(db, sneaker, offset):
    with pytest.raises(HTTPException) as error:
        get_product(sneaker.id + offset, db=db)

    assert error.value.status_code == 404
    assert error.value.detail == f"SKU {sneaker.id + offset} not found"
