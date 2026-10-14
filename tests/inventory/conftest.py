"""Fixtures del inventario (CONTEXT-9).

Supabase se sustituye por un SQLite en memoria con las claves foráneas activadas (SQLite
las ignora si no se pide), creado con los mismos modelos SQLModel. Los usuarios siguen
siendo usuarios reales de TinyDB, como en la aplicación.
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import services.api.main as main
import services.models  # noqa: F401 — registra las tablas en SQLModel.metadata
from services import inventory_service
from services.api import user_service
from services.api.security import create_access_token
from services.database import get_db
from services.schemas import SKUCreate, StockEntryCreate, StockExitCreate

SNEAKER = {
    "name": "Zapatilla blanca clásica - Talla 42",
    "sku": "CLT-SNK-W-42",
    "client_name": "PureStep Footwear",
    "category": "fashion",
    "warehouse": "LA",
}


@pytest.fixture
def engine():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def enforce_foreign_keys(dbapi_connection, _):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    SQLModel.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db(engine):
    with Session(engine) as session:
        yield session


@pytest.fixture
def operator():
    """Operario de almacén: usuario real de TinyDB."""
    user, _ = user_service.create_user(f"operario-{uuid.uuid4().hex[:8]}@trackflow.com", "s3cret-password")
    return user


@pytest.fixture
def api(engine, operator):
    """Cliente HTTP autenticado como `operator`, con el inventario en el SQLite de pruebas."""

    def test_db():
        with Session(engine) as session:
            yield session

    main.app.dependency_overrides[get_db] = test_db
    yield TestClient(main.app, headers={"Authorization": f"Bearer {create_access_token(operator['id'])}"})
    main.app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def make_sku(db):
    def _make(**overrides):
        return inventory_service.create_sku(db, SKUCreate(**{**SNEAKER, **overrides}))

    return _make


@pytest.fixture
def sneaker(make_sku):
    return make_sku()


@pytest.fixture
def receive(db, operator):
    """Registra una entrada de stock (por defecto en el almacén del SKU)."""

    def _receive(sku, quantity, warehouse=None, reference="PO-2024-0098"):
        data = StockEntryCreate(
            sku_id=sku.id, quantity=quantity, reference=reference, warehouse=warehouse or sku.warehouse
        )
        return inventory_service.register_entry(db, data, operator["id"])

    return _receive


@pytest.fixture
def dispatch(db, operator):
    """Registra una salida de stock (por defecto un despacho en el almacén del SKU)."""

    def _dispatch(sku, quantity, warehouse=None, exit_type="dispatch", tracking_number="1Z999AA10123456784"):
        data = StockExitCreate(
            sku_id=sku.id,
            quantity=quantity,
            exit_type=exit_type,
            tracking_number=tracking_number if exit_type == "dispatch" else None,
            warehouse=warehouse or sku.warehouse,
        )
        return inventory_service.register_exit(db, data, operator["id"])

    return _dispatch
