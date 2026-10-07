"""Fixtures de las pruebas unitarias del gestor de incidencias (API-042).

Como en tests/auth, se llama directamente a las funciones de ruta y a los servicios: sin
TestClient ni serialización HTTP. La capa semántica usa el proveedor "hashing" que fija
tests/conftest.py (determinista y sin descargar ningún modelo).
"""

import pytest
from fastapi import BackgroundTasks

from services.api import embeddings, incident_service, store
from services.api.routes import incidents as incident_routes

VALID = {
    "title": "Palé dañado en muelle 3",
    "description": "La carretilla golpeó un palé de mercancía durante la descarga.",
    "category": "warehouse_incident",
    "origin": "branch",
    "branch": "zaragoza_warehouse",
}

# Dos problemas sin palabras en común: con "hashing" no se parecen entre sí.
LOST_PARCEL = {
    "title": "Paquete perdido en reparto",
    "description": "El cliente no ha recibido su paquete y el transportista no consigue localizarlo.",
    "category": "lost_parcel",
    "origin": "customer",
    "branch": "zaragoza_office",
}
SYSTEM_FAILURE = {
    "title": "Fallo de sincronización del WMS",
    "description": "El software del almacén dejó de actualizar el inventario desde esta mañana.",
    "category": "system_failure",
    "origin": "internal",
    "branch": "la_warehouse",
}


@pytest.fixture(autouse=True)
def empty_incidents():
    store.clear_incidents()
    yield
    store.clear_incidents()


@pytest.fixture
def incident_payload():
    return lambda **overrides: {**VALID, **overrides}


@pytest.fixture
def make_incident(incident_payload):
    def _make(**overrides):
        return incident_routes.create_incident(BackgroundTasks(), incident_payload(**overrides))

    return _make


@pytest.fixture
def set_clock(monkeypatch):
    """Fija el instante que las rutas usan como `created_at` / `updated_at`."""
    return lambda timestamp: monkeypatch.setattr(incident_routes, "_now_utc", lambda: timestamp)


@pytest.fixture
def broken_embeddings(monkeypatch):
    """El proveedor de embeddings falla en cada llamada."""

    def unavailable(*args, **kwargs):
        raise embeddings.EmbeddingsUnavailable("proveedor caído")

    monkeypatch.setattr(incident_service, "embed", unavailable)


@pytest.fixture
def error_codes():
    """{(campo, código)} de un IncidentValidationError capturado con pytest.raises."""
    return lambda error: {(item["field"], item["code"]) for item in error.value.errors}


@pytest.fixture
def lost_parcel():
    return dict(LOST_PARCEL)


@pytest.fixture
def system_failure():
    return dict(SYSTEM_FAILURE)
