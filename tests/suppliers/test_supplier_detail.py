"""GET /suppliers/{id} — get_supplier."""

import pytest
from fastapi import HTTPException

from services.api.routes.suppliers import delete_supplier, get_supplier


def _assert_not_found(supplier_id):
    with pytest.raises(HTTPException) as error:
        get_supplier(supplier_id)
    assert error.value.status_code == 404
    assert error.value.detail == f"Supplier {supplier_id} not found"


# =========================================================
# Camino feliz
# =========================================================


def test_get_supplier_returns_the_stored_supplier(make_supplier):
    created = make_supplier(notes="Recogida diaria")

    assert get_supplier(created["id"]) == created


def test_get_supplier_picks_the_right_one_among_several(make_supplier):
    make_supplier(name="Uno")
    second = make_supplier(name="Dos")

    assert get_supplier(second["id"])["name"] == "Dos"


# =========================================================
# Casos límite
# =========================================================


@pytest.mark.parametrize("supplier_id", [0, -1])
def test_get_supplier_with_non_positive_id_is_not_found(make_supplier, supplier_id):
    make_supplier()

    _assert_not_found(supplier_id)


# =========================================================
# Modos de fallo
# =========================================================


def test_get_unknown_supplier_is_not_found(make_supplier):
    created = make_supplier()

    _assert_not_found(created["id"] + 1000)


def test_get_deleted_supplier_is_not_found(make_supplier):
    created = make_supplier()
    delete_supplier(created["id"])

    _assert_not_found(created["id"])
