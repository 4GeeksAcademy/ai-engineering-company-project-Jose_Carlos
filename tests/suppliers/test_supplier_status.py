"""PATCH /suppliers/{id}/status — update_status y StatusUpdate."""

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from services.api import store
from services.api.models import StatusUpdate
from services.api.routes.suppliers import update_status

CREATED_AT = "2026-10-01T08:00:00+00:00"
LATER = "2026-10-07T10:00:00+00:00"


@pytest.fixture
def supplier(make_supplier, set_clock):
    set_clock(CREATED_AT)
    created = make_supplier()
    set_clock(LATER)
    return created


# =========================================================
# Camino feliz
# =========================================================


def test_suspend_and_reactivate_a_supplier(supplier):
    suspended = update_status(supplier["id"], StatusUpdate(status="suspended"))
    assert suspended["status"] == "suspended"
    assert store.get_supplier_by_id(supplier["id"])["status"] == "suspended"

    reactivated = update_status(supplier["id"], StatusUpdate(status="active"))
    assert reactivated["status"] == "active"


# =========================================================
# Casos límite
# =========================================================


def test_status_change_does_not_touch_the_rate_timestamp(supplier):
    # updated_at es la fecha de la última TARIFA: suspender no debe renovarla.
    updated = update_status(supplier["id"], StatusUpdate(status="suspended"))

    assert updated["updated_at"] == CREATED_AT
    assert {**updated, "status": "active"} == supplier


def test_setting_the_same_status_again_changes_nothing(supplier):
    assert update_status(supplier["id"], StatusUpdate(status="active")) == supplier


def test_status_change_only_touches_the_given_supplier(supplier, make_supplier):
    other = make_supplier(name="Otro")

    update_status(supplier["id"], StatusUpdate(status="suspended"))

    assert store.get_supplier_by_id(other["id"])["status"] == "active"


# =========================================================
# Modos de fallo
# =========================================================


@pytest.mark.parametrize("payload", [
    {"status": "archived"},
    {"status": "ACTIVE"},
    {"status": ""},
    {"status": None},
    {},
])
def test_update_status_rejects_invalid_status(supplier, payload):
    with pytest.raises(ValidationError):
        StatusUpdate.model_validate(payload)

    assert store.get_supplier_by_id(supplier["id"]) == supplier


def test_update_status_of_unknown_supplier_is_not_found(supplier):
    with pytest.raises(HTTPException) as error:
        update_status(supplier["id"] + 1000, StatusUpdate(status="suspended"))

    assert error.value.status_code == 404
    assert store.get_all_suppliers() == [supplier]
