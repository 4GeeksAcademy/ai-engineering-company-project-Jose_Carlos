"""PATCH /suppliers/{id}/rate — update_rate y RateUpdate."""

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from services.api import store
from services.api.models import RateUpdate
from services.api.routes.suppliers import update_rate

CREATED_AT = "2026-10-01T08:00:00+00:00"
CHANGED_AT = "2026-10-07T10:00:00+00:00"


@pytest.fixture
def supplier(make_supplier, set_clock):
    set_clock(CREATED_AT)
    created = make_supplier(rate_per_shipment=4.5)
    set_clock(CHANGED_AT)
    return created


# =========================================================
# Camino feliz
# =========================================================


def test_update_rate_changes_the_rate_and_its_timestamp(supplier):
    updated = update_rate(supplier["id"], RateUpdate(rate_per_shipment=5.25))

    assert updated["rate_per_shipment"] == 5.25
    assert updated["updated_at"] == CHANGED_AT
    assert store.get_supplier_by_id(supplier["id"]) == updated


# =========================================================
# Casos límite
# =========================================================


def test_update_rate_leaves_every_other_field_untouched(supplier):
    updated = update_rate(supplier["id"], RateUpdate(rate_per_shipment=5.25))

    untouched = set(supplier) - {"rate_per_shipment", "updated_at"}
    assert {key: updated[key] for key in untouched} == {key: supplier[key] for key in untouched}


def test_confirming_the_same_rate_still_renews_the_timestamp(supplier):
    updated = update_rate(supplier["id"], RateUpdate(rate_per_shipment=4.5))

    assert updated["rate_per_shipment"] == 4.5
    assert updated["updated_at"] == CHANGED_AT


def test_update_rate_only_touches_the_given_supplier(supplier, make_supplier):
    other = make_supplier(name="Otro", rate_per_shipment=9)

    update_rate(supplier["id"], RateUpdate(rate_per_shipment=5.25))

    assert store.get_supplier_by_id(other["id"]) == other


def test_update_rate_accepts_integers_as_floats(supplier):
    assert update_rate(supplier["id"], RateUpdate(rate_per_shipment=5))["rate_per_shipment"] == 5.0


# =========================================================
# Modos de fallo
# =========================================================


@pytest.mark.parametrize("rate", [0, -0.01, "caro", None, float("inf"), float("nan")])
def test_update_rate_rejects_invalid_rate(supplier, rate):
    with pytest.raises(ValidationError):
        RateUpdate.model_validate({"rate_per_shipment": rate})

    assert store.get_supplier_by_id(supplier["id"]) == supplier


def test_update_rate_requires_the_rate():
    with pytest.raises(ValidationError):
        RateUpdate.model_validate({})


def test_update_rate_of_unknown_supplier_is_not_found(supplier):
    with pytest.raises(HTTPException) as error:
        update_rate(supplier["id"] + 1000, RateUpdate(rate_per_shipment=5.25))

    assert error.value.status_code == 404
    assert store.get_all_suppliers() == [supplier]
