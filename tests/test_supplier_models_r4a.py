"""Port de las 42 aserciones de R4-A sobre los modelos Supplier (U-A3 d).

Origen: audit/evidence/dynamic/r4a/sup_model_checks.py y su salida sup_model_checks.output.json
(R4-A: 53 casos = 42 con veredicto esperado, todos PASS, + 11 "observe" sin expectativa).
Aquí se portan exactamente los 42 casos con expectativa: mismos ids, modelos, payloads y veredicto
(aceptado / rechazado), más las propiedades adicionales que R4-A comprobaba en el mismo caso.
Los 11 casos "observe" no se portan: R4-A no les asignó comportamiento esperado.

Solo se importa services/api/models.py; nunca services/api/database.py (no se crea db.json).
"""

import pytest
from pydantic import ValidationError

from services.api import models as m

BASE = {
    "name": "AUDIT-R4 Supplier",
    "country": "USA",
    "categories": ["carrier_last_mile"],
    "rate_per_shipment": 10.5,
    "currency": "USD",
    "status": "active",
}
ALL8 = ["carrier_last_mile", "carrier_international", "warehouse_supplies", "packaging_materials",
        "reverse_logistics", "fleet_maintenance", "it_and_wms_software", "cleaning_and_facilities"]


def without(key):
    return {k: v for k, v in BASE.items() if k != key}


def with_(**kw):
    return {**BASE, **kw}


# Propiedades adicionales que R4-A evaluaba dentro del mismo caso.
def no_updated_at(obj, errors):
    assert not hasattr(obj, "updated_at")
    assert "updated_at" not in obj.model_dump()


def optionals_none(obj, errors):
    assert (obj.service_zone, obj.contact_email, obj.notes) == (None, None, None)


def optionals_preserved(obj, errors):
    assert (obj.service_zone, obj.contact_email, obj.notes) == ("Zone A", "audit-r4@example.invalid", "audit note")


def validator_message(text):
    def check(obj, errors):
        assert any(text in e["msg"] for e in errors)
    return check


C, S, R = "SupplierCreate", "SupplierStatusUpdate", "SupplierRateUpdate"

CASES = [
    # SUP-001 campos obligatorios; updated_at no aceptado
    ("SUP001-HP-01", C, BASE, "accept", None),
    ("SUP001-CR-01", C, without("name"), "reject", None),
    ("SUP001-CR-02", C, without("country"), "reject", None),
    ("SUP001-CR-03", C, without("categories"), "reject", None),
    ("SUP001-CR-04", C, without("rate_per_shipment"), "reject", None),
    ("SUP001-CR-05", C, without("currency"), "reject", None),
    ("SUP001-CR-06", C, without("status"), "reject", None),
    ("SUP001-CR-07", C, with_(updated_at="2000-01-01T00:00:00"), "accept", no_updated_at),
    # SUP-002 opcionales
    ("SUP002-HP-01", C, BASE, "accept", optionals_none),
    ("SUP002-HP-02", C, with_(service_zone="Zone A", contact_email="audit-r4@example.invalid", notes="audit note"), "accept", optionals_preserved),
    # SUP-003 categorías
    ("SUP003-CR-01", C, with_(categories=[]), "reject", None),
    ("SUP003-CR-02", C, with_(categories=["invented"]), "reject", None),
    ("SUP003-CR-03", C, with_(categories=["carrier_last_mile", "invented"]), "reject", None),
    ("SUP003-HP-01", C, with_(categories=["carrier_last_mile", "reverse_logistics"]), "accept", None),
    ("SUP003-HP-02", C, with_(categories=ALL8), "accept", None),
    # SUP-004 estado (alta y actualización de estado)
    ("SUP004-CR-01", C, with_(status="deleted"), "reject", None),
    ("SUP004-CR-03", S, {"status": "deleted"}, "reject", None),
    ("SUP004-CR-02", C, with_(status="Active"), "reject", None),
    ("SUP004-CR-04", S, {"status": "Active"}, "reject", None),
    ("SUP004-HP-01", C, with_(status="active"), "accept", None),
    ("SUP004-HP-03", S, {"status": "active"}, "accept", None),
    ("SUP004-HP-02", C, with_(status="suspended"), "accept", None),
    ("SUP004-HP-04", S, {"status": "suspended"}, "accept", None),
    ("SUP004-ED-01", C, with_(status=None), "reject", None),
    ("SUP004-ED-02", S, {"status": None}, "reject", None),
    # SUP-005 país
    ("SUP005-CR-01", C, with_(country="United States"), "reject", None),
    ("SUP005-CR-02", C, with_(country="US"), "reject", None),
    ("SUP005-CR-03", C, with_(country="spain"), "reject", None),
    ("SUP005-HP-01", C, with_(country="USA", currency="USD"), "accept", None),
    ("SUP005-HP-02", C, with_(country="Spain", currency="EUR"), "accept", None),
    # SUP-006 tarifa > 0 (alta y actualización de tarifa)
    ("SUP006-CR-C1", C, with_(rate_per_shipment=0), "reject", None),
    ("SUP006-CR-C2", C, with_(rate_per_shipment=-1), "reject", None),
    ("SUP006-HP-C1", C, with_(rate_per_shipment=0.01), "accept", None),
    ("SUP006-ED-C4", C, with_(rate_per_shipment=-0.0), "reject", None),
    ("SUP006-CR-U1", R, {"rate_per_shipment": 0}, "reject", None),
    ("SUP006-CR-U2", R, {"rate_per_shipment": -1}, "reject", None),
    ("SUP006-HP-U1", R, {"rate_per_shipment": 0.01}, "accept", None),
    ("SUP006-ED-U4", R, {"rate_per_shipment": -0.0}, "reject", None),
    # SUP-007 coherencia país–moneda en el alta
    ("SUP007-CR-01", C, with_(country="USA", currency="EUR"), "reject", validator_message("USA suppliers must use USD")),
    ("SUP007-CR-02", C, with_(country="Spain", currency="USD"), "reject", validator_message("Spain suppliers must use EUR")),
    ("SUP007-HP-01", C, with_(country="USA", currency="USD"), "accept", None),
    ("SUP007-HP-02", C, with_(country="Spain", currency="EUR"), "accept", None),
]


def test_r4a_case_count_is_42():
    assert len(CASES) == 42
    assert len({c[0] for c in CASES}) == 42


@pytest.mark.parametrize(("test_id", "model_name", "payload", "expect", "extra"), CASES, ids=[c[0] for c in CASES])
def test_r4a_supplier_assertion(test_id, model_name, payload, expect, extra):
    model = getattr(m, model_name)
    obj, errors = None, []
    try:
        obj = model(**payload)
        observed = "accept"
    except ValidationError as e:
        observed = "reject"
        errors = e.errors()

    assert observed == expect, f"{test_id}: {model_name} {observed}ed, R4-A expected {expect}"
    if extra is not None:
        extra(obj, errors)
