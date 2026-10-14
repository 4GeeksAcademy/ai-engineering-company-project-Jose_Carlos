"""POST /inventory/orders/outbound — despachos y pérdidas (StockExit)."""

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlmodel import select

from services.models import StockExit
from services.routers.inventory import get_product, register_outbound
from services.schemas import StockExitCreate, StockExitRead


def _exit(sku, **overrides):
    payload = {
        "sku_id": sku.id, "quantity": 30, "exit_type": "dispatch",
        "tracking_number": "1Z999AA10123456784", "warehouse": sku.warehouse, **overrides,
    }
    return StockExitCreate(**payload)


def _loss(sku, **overrides):
    return _exit(sku, exit_type="loss", tracking_number=None, **overrides)


@pytest.fixture
def stocked(sneaker, receive):
    """SKU de LA con 100 unidades en LA y 10 en ZGZ."""
    receive(sneaker, 100, warehouse="LA")
    receive(sneaker, 10, warehouse="ZGZ")
    return sneaker


# =========================================================
# Camino feliz
# =========================================================


def test_dispatch_reduces_stock_and_is_traceable_to_its_user(db, stocked, operator):
    stock_exit = register_outbound(_exit(stocked), current_user=operator, db=db)

    assert isinstance(stock_exit, StockExitRead)
    assert stock_exit.order_type == "outbound"
    assert (stock_exit.exit_type, stock_exit.tracking_number) == ("dispatch", "1Z999AA10123456784")
    assert stock_exit.user_uuid == operator["id"]
    assert stock_exit.sku.sku == "CLT-SNK-W-42"
    assert get_product(stocked.id, db=db).current_stock == 70


def test_loss_reduces_stock_without_tracking_number(db, stocked, operator):
    stock_exit = register_outbound(_loss(stocked, quantity=2), current_user=operator, db=db)

    assert (stock_exit.exit_type, stock_exit.tracking_number) == ("loss", None)
    assert get_product(stocked.id, db=db).current_stock == 98


# =========================================================
# Casos límite
# =========================================================


def test_exit_can_take_the_stock_exactly_to_zero(db, stocked, operator):
    register_outbound(_exit(stocked, quantity=100), current_user=operator, db=db)

    assert get_product(stocked.id, db=db).stock_by_warehouse == {"LA": 0, "ZGZ": 10}


def test_exit_only_draws_from_its_own_warehouse(db, stocked, operator):
    register_outbound(_loss(stocked, quantity=10, warehouse="ZGZ"), current_user=operator, db=db)

    assert get_product(stocked.id, db=db).stock_by_warehouse == {"LA": 100, "ZGZ": 0}


def test_successive_exits_are_checked_against_the_remaining_stock(db, stocked, operator):
    register_outbound(_exit(stocked, quantity=60), current_user=operator, db=db)

    with pytest.raises(HTTPException) as error:
        register_outbound(_exit(stocked, quantity=41), current_user=operator, db=db)

    assert error.value.detail == "Insufficient stock for SKU 'CLT-SNK-W-42'. Available: 40, requested: 41."


def test_tracking_number_is_trimmed(stocked):
    assert _exit(stocked, tracking_number="  1Z999  ").tracking_number == "1Z999"


# =========================================================
# Modos de fallo
# =========================================================


def test_exit_beyond_the_warehouse_stock_is_rejected_before_writing(db, stocked, operator):
    with pytest.raises(HTTPException) as error:
        register_outbound(_exit(stocked, quantity=101), current_user=operator, db=db)

    assert error.value.status_code == 400
    assert error.value.detail == "Insufficient stock for SKU 'CLT-SNK-W-42'. Available: 100, requested: 101."
    assert db.exec(select(StockExit)).all() == []
    assert get_product(stocked.id, db=db).current_stock == 100


def test_stock_of_the_other_warehouse_does_not_cover_an_exit(db, stocked, operator):
    # 110 unidades en total, pero solo 10 en ZGZ: el stock es por almacén.
    with pytest.raises(HTTPException) as error:
        register_outbound(_exit(stocked, quantity=11, warehouse="ZGZ"), current_user=operator, db=db)

    assert error.value.status_code == 400
    assert "Available: 10, requested: 11." in error.value.detail


def test_exit_from_a_sku_without_stock_is_rejected(db, sneaker, operator):
    with pytest.raises(HTTPException) as error:
        register_outbound(_loss(sneaker, quantity=1), current_user=operator, db=db)

    assert error.value.status_code == 400
    assert error.value.detail == "Insufficient stock for SKU 'CLT-SNK-W-42'. Available: 0, requested: 1."


def test_exit_for_unknown_sku_is_not_found(db, stocked, operator):
    with pytest.raises(HTTPException) as error:
        register_outbound(_exit(stocked, sku_id=stocked.id + 1000), current_user=operator, db=db)

    assert error.value.status_code == 404
    assert db.exec(select(StockExit)).all() == []


def test_dispatch_without_tracking_number_is_a_validation_error(stocked):
    with pytest.raises(ValidationError, match="tracking_number is required"):
        _exit(stocked, tracking_number=None)


@pytest.mark.parametrize("blank", ["", "   "])
def test_dispatch_with_blank_tracking_number_is_a_validation_error(stocked, blank):
    with pytest.raises(ValidationError):
        _exit(stocked, tracking_number=blank)


def test_loss_with_tracking_number_is_a_validation_error(stocked):
    with pytest.raises(ValidationError, match="must be null"):
        _exit(stocked, exit_type="loss")


@pytest.mark.parametrize("overrides", [
    {"exit_type": "return"},
    {"quantity": 0},
    {"quantity": -1},
    {"quantity": "5"},
    {"warehouse": "BCN"},
    {"user_uuid": "someone-else"},
])
def test_exit_rejects_invalid_fields(stocked, overrides):
    with pytest.raises(ValidationError):
        _exit(stocked, **overrides)
