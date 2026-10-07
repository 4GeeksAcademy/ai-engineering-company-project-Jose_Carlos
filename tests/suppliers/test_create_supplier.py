"""POST /suppliers — create_supplier y SupplierCreate."""

import pytest
from pydantic import ValidationError

from services.api import store
from services.api.models import SupplierCreate, SupplierResponse
from services.api.routes.suppliers import create_supplier


# =========================================================
# Camino feliz
# =========================================================


def test_create_supplier_stores_it_with_server_side_id_and_timestamp(supplier_payload, set_clock):
    set_clock("2026-10-07T10:00:00+00:00")

    created = create_supplier(SupplierCreate(**supplier_payload()))

    assert created["id"] >= 1
    assert created["updated_at"] == "2026-10-07T10:00:00+00:00"
    assert {key: created[key] for key in supplier_payload()} == supplier_payload()
    assert store.get_supplier_by_id(created["id"]) == created


def test_created_supplier_fits_the_response_model(make_supplier):
    body = SupplierResponse.model_validate(make_supplier()).model_dump(mode="json")

    assert body["status"] == "active"
    assert body["categories"] == ["carrier_last_mile"]


def test_create_usa_supplier_in_dollars(make_supplier):
    created = make_supplier(name="LA Freight", country="USA", currency="USD")

    assert (created["country"], created["currency"]) == ("USA", "USD")


# =========================================================
# Casos límite
# =========================================================


def test_create_ignores_id_and_updated_at_sent_by_client(supplier_payload, set_clock):
    set_clock("2026-10-07T10:00:00+00:00")
    body = SupplierCreate.model_validate(
        supplier_payload(id=999, updated_at="2000-01-01T00:00:00+00:00")
    )

    created = create_supplier(body)

    assert created["id"] != 999
    assert created["updated_at"] == "2026-10-07T10:00:00+00:00"


def test_create_without_optional_fields_stores_them_as_none(make_supplier):
    created = make_supplier()

    assert (created["service_zone"], created["contact_email"], created["notes"]) == (None, None, None)


def test_create_keeps_every_category_and_optional_field(make_supplier):
    created = make_supplier(
        categories=["carrier_last_mile", "reverse_logistics"],
        service_zone="Aragón",
        contact_email="ops@ebro.example",
        notes="Recogida diaria",
    )

    assert created["categories"] == ["carrier_last_mile", "reverse_logistics"]
    assert created["service_zone"] == "Aragón"
    assert created["contact_email"] == "ops@ebro.example"
    assert created["notes"] == "Recogida diaria"


def test_create_accepts_the_smallest_positive_rate(make_supplier):
    assert make_supplier(rate_per_shipment=0.01)["rate_per_shipment"] == 0.01


def test_two_suppliers_get_different_ids(make_supplier):
    first, second = make_supplier(name="Uno"), make_supplier(name="Dos")

    assert first["id"] != second["id"]
    assert len(store.get_all_suppliers()) == 2


# =========================================================
# Modos de fallo
# =========================================================


@pytest.mark.parametrize("overrides", [
    {"country": "Spain", "currency": "USD"},
    {"country": "USA", "currency": "EUR"},
    {"country": "France"},
    {"currency": "GBP"},
    {"rate_per_shipment": 0},
    {"rate_per_shipment": -1},
    {"rate_per_shipment": "caro"},
    {"categories": []},
    {"categories": ["teleportation"]},
    {"status": "archived"},
    {"name": ""},
    {"name": None},
])
def test_create_rejects_invalid_supplier(supplier_payload, overrides):
    with pytest.raises(ValidationError):
        SupplierCreate.model_validate(supplier_payload(**overrides))

    assert store.get_all_suppliers() == []


@pytest.mark.parametrize("missing", ["name", "country", "categories", "rate_per_shipment", "currency", "status"])
def test_create_requires_every_mandatory_field(supplier_payload, missing):
    payload = supplier_payload()
    del payload[missing]

    with pytest.raises(ValidationError):
        SupplierCreate.model_validate(payload)


@pytest.mark.parametrize("rate", [float("inf"), float("nan")])
def test_create_rejects_non_finite_rate(supplier_payload, rate):
    # Un JSON con `1e999` llega como infinito: se guardaba y la API lo devolvía como null.
    with pytest.raises(ValidationError):
        SupplierCreate.model_validate(supplier_payload(rate_per_shipment=rate))


@pytest.mark.parametrize("blank", ["   ", "\t", "\n"])
def test_create_rejects_name_made_only_of_whitespace(supplier_payload, blank):
    with pytest.raises(ValidationError):
        SupplierCreate.model_validate(supplier_payload(name=blank))
