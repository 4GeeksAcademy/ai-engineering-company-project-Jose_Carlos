"""DELETE /suppliers/{id} — delete_supplier."""

import pytest
from fastapi import HTTPException

from services.api import store
from services.api.models import StatusUpdate
from services.api.routes.suppliers import delete_supplier, update_status


def _assert_not_found(supplier_id):
    with pytest.raises(HTTPException) as error:
        delete_supplier(supplier_id)
    assert error.value.status_code == 404
    assert error.value.detail == f"Supplier {supplier_id} not found"


# =========================================================
# Camino feliz
# =========================================================


def test_delete_returns_the_supplier_as_it_was_and_removes_it(make_supplier):
    created = make_supplier()

    deleted = delete_supplier(created["id"])

    assert deleted == created
    assert store.get_supplier_by_id(created["id"]) is None
    assert store.get_all_suppliers() == []


# =========================================================
# Casos límite
# =========================================================


def test_delete_leaves_the_other_suppliers_alone(make_supplier):
    first, second, third = make_supplier(name="Uno"), make_supplier(name="Dos"), make_supplier(name="Tres")

    delete_supplier(second["id"])

    assert store.get_all_suppliers() == [first, third]


def test_delete_returns_the_latest_state_of_the_supplier(make_supplier):
    created = make_supplier()
    update_status(created["id"], StatusUpdate(status="suspended"))

    assert delete_supplier(created["id"])["status"] == "suspended"


# =========================================================
# Modos de fallo
# =========================================================


def test_deleting_twice_is_not_found_the_second_time(make_supplier):
    created = make_supplier()
    delete_supplier(created["id"])

    _assert_not_found(created["id"])


@pytest.mark.parametrize("offset", [1000, -1000])
def test_delete_unknown_supplier_is_not_found_and_deletes_nothing(make_supplier, offset):
    created = make_supplier()

    _assert_not_found(created["id"] + offset)
    assert store.get_all_suppliers() == [created]
