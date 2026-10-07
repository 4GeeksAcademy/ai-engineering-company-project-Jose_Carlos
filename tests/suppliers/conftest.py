"""Fixtures de las pruebas unitarias de proveedores (API-042).

Como en tests/auth, se llama directamente a las funciones de ruta y al store: sin
TestClient ni serialización HTTP.
"""

import pytest

from services.api import store
from services.api.models import SupplierCreate
from services.api.routes import suppliers as supplier_routes

VALID = {
    "name": "Transportes Ebro",
    "country": "Spain",
    "categories": ["carrier_last_mile"],
    "rate_per_shipment": 4.5,
    "currency": "EUR",
    "status": "active",
}


@pytest.fixture(autouse=True)
def empty_suppliers():
    store.clear_suppliers()
    yield
    store.clear_suppliers()


@pytest.fixture
def supplier_payload():
    return lambda **overrides: {**VALID, **overrides}


@pytest.fixture
def make_supplier(supplier_payload):
    def _make(**overrides):
        return supplier_routes.create_supplier(SupplierCreate(**supplier_payload(**overrides)))

    return _make


@pytest.fixture
def set_clock(monkeypatch):
    """Fija el instante que las rutas usan como `updated_at`."""
    return lambda timestamp: monkeypatch.setattr(supplier_routes, "_now_utc", lambda: timestamp)
