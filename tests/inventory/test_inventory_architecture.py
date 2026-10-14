"""Criterios de aceptación de la arquitectura: dos bases de datos, FK en la base de datos,
stock nunca almacenado, schemas separados del ORM, sesión por petición y rutas bajo /inventory."""

import inspect
import uuid
from typing import get_args

import pytest
from fastapi.routing import APIRoute
from pydantic import BaseModel
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlmodel import Session, SQLModel

import services.api.main as main
from services import database, models, schemas
from services.api import store
from services.models import SKU, StockEntry, StockExit
from services.routers import inventory


# =========================================================
# Dos conexiones
# =========================================================


def test_auth_stays_in_tinydb_and_inventory_uses_the_sqlmodel_engine():
    assert store.db is database.tinydb
    assert str(database.TINYDB_PATH).endswith("db.json")
    # En los tests DATABASE_URL apunta a SQLite; en la aplicación, a Supabase.
    assert database.engine.url.render_as_string() == database.DATABASE_URL


@pytest.mark.parametrize("given,expected", [
    ("postgresql://u:p@host:5432/postgres", "postgresql+psycopg://u:p@host:5432/postgres"),
    ("postgres://u:p@host:6543/postgres", "postgresql+psycopg://u:p@host:6543/postgres"),
    ("postgresql+psycopg://u:p@host/db", "postgresql+psycopg://u:p@host/db"),
    ("sqlite://", "sqlite://"),
])
def test_supabase_connection_strings_use_the_psycopg_driver(given, expected):
    assert database._engine_url(given) == expected


def test_prepared_statements_are_disabled_only_for_postgres():
    assert database._connect_args("postgresql+psycopg://u:p@host/db") == {"prepare_threshold": None}
    assert database._connect_args("sqlite://") == {}


def test_database_url_password_never_appears_in_messages(monkeypatch):
    monkeypatch.setattr(database, "DATABASE_URL", "postgresql+psycopg://postgres.ref:sup3r-secret@pooler.supabase.com:5432/postgres")

    assert "sup3r-secret" not in database.safe_database_url()
    assert "pooler.supabase.com" in database.safe_database_url()


def test_unreachable_supabase_at_startup_fails_with_a_clear_message_without_password(monkeypatch):
    monkeypatch.setattr(database, "DATABASE_URL", "postgresql+psycopg://postgres.ref:sup3r-secret@pooler.supabase.com:5432/postgres")

    def unreachable(*args, **kwargs):
        raise OperationalError("connect", {}, Exception("connection refused"))

    monkeypatch.setattr(SQLModel.metadata, "create_all", unreachable)

    with pytest.raises(RuntimeError) as error:
        database.create_db_and_tables()

    assert "DATABASE_URL" in str(error.value)
    assert "sup3r-secret" not in str(error.value)


def test_app_creates_the_inventory_schema_on_startup(monkeypatch):
    called = []
    monkeypatch.setattr(main, "create_db_and_tables", lambda: called.append(True))

    from fastapi.testclient import TestClient

    with TestClient(main.app):
        pass

    assert called == [True]


# =========================================================
# Sesión por petición
# =========================================================


def test_get_db_yields_a_fresh_session_per_request_and_closes_it(monkeypatch):
    closed = []
    original_close = Session.close

    def tracking_close(self):
        closed.append(self)
        original_close(self)

    monkeypatch.setattr(Session, "close", tracking_close)

    first_request, second_request = database.get_db(), database.get_db()
    first, second = next(first_request), next(second_request)
    assert isinstance(first, Session) and first is not second

    first_request.close()
    second_request.close()
    assert first in closed and second in closed


def test_no_module_keeps_a_global_session():
    for module in (database, inventory, models, schemas):
        assert not any(isinstance(value, Session) for value in vars(module).values()), module.__name__


def test_every_inventory_endpoint_receives_its_session_through_depends():
    for route in inventory.router.routes:
        dependency_calls = [dependency.call for dependency in route.dependant.dependencies]
        assert database.get_db in dependency_calls, route.path


# =========================================================
# Esquema en la base de datos
# =========================================================


def test_sku_table_has_no_stock_column(engine):
    columns = {column["name"] for column in sa_inspect(engine).get_columns("sku")}

    assert columns == {"id", "name", "sku", "client_name", "category", "warehouse"}
    assert not any("stock" in column for column in columns)


@pytest.mark.parametrize("table", ["stock_entry", "stock_exit"])
def test_movements_reference_the_sku_with_a_database_foreign_key(engine, table):
    [foreign_key] = sa_inspect(engine).get_foreign_keys(table)

    assert foreign_key["constrained_columns"] == ["sku_id"]
    assert foreign_key["referred_table"] == "sku"
    assert foreign_key["referred_columns"] == ["id"]


def test_no_user_table_is_replicated_in_the_inventory_database(engine):
    assert set(sa_inspect(engine).get_table_names()) == {"sku", "stock_entry", "stock_exit"}
    # user_uuid es texto sin FK: apunta a TinyDB, no a una tabla de Supabase.
    for table in ("stock_entry", "stock_exit"):
        assert all(fk["constrained_columns"] != ["user_uuid"] for fk in sa_inspect(engine).get_foreign_keys(table))


def test_database_rejects_a_movement_for_a_missing_sku(db):
    db.add(StockEntry(sku_id=999, quantity=1, reference="PO-1", warehouse="LA", user_uuid=str(uuid.uuid4())))

    with pytest.raises(IntegrityError):
        db.commit()


@pytest.mark.parametrize("row", [
    {"quantity": 0},
    {"quantity": -3},
    {"warehouse": "MAD"},
    {"exit_type": "return"},
    {"exit_type": "dispatch", "tracking_number": None},
    {"exit_type": "loss", "tracking_number": "1Z999"},
])
def test_database_check_constraints_reject_impossible_exits(db, sneaker, row):
    values = {"sku_id": sneaker.id, "quantity": 1, "exit_type": "dispatch", "tracking_number": "1Z999",
              "warehouse": "LA", "user_uuid": "u", **row}
    db.add(StockExit(**values))

    with pytest.raises(IntegrityError):
        db.commit()


@pytest.mark.parametrize("row", [{"category": "food"}, {"warehouse": "BCN"}])
def test_database_check_constraints_reject_impossible_skus(db, row):
    db.add(SKU(**{"name": "X", "sku": f"X-{uuid.uuid4().hex[:6]}", "client_name": "C",
                  "category": "fashion", "warehouse": "LA", **row}))

    with pytest.raises(IntegrityError):
        db.commit()


def test_sku_code_is_unique_in_the_database(db, sneaker):
    db.add(SKU(name="Otra", sku=sneaker.sku, client_name="C", category="fashion", warehouse="ZGZ"))

    with pytest.raises(IntegrityError):
        db.commit()


# =========================================================
# ORM y schemas separados
# =========================================================


def test_schemas_are_plain_pydantic_models_not_orm_tables():
    schema_classes = [obj for _, obj in inspect.getmembers(schemas, inspect.isclass) if obj.__module__ == schemas.__name__]

    assert schema_classes
    for schema in schema_classes:
        assert issubclass(schema, BaseModel)
        assert not issubclass(schema, SQLModel), schema.__name__


def test_allowed_values_are_the_same_in_schemas_and_database():
    assert get_args(schemas.Category) == models.CATEGORIES
    assert get_args(schemas.Warehouse) == models.WAREHOUSES
    assert get_args(schemas.ExitType) == models.EXIT_TYPES


def test_no_endpoint_returns_an_orm_object():
    for route in inventory.router.routes:
        assert isinstance(route, APIRoute)
        response_types = get_args(route.response_model) or (route.response_model,)
        for response_type in response_types:
            for model in get_args(response_type) or (response_type,):
                assert not (isinstance(model, type) and issubclass(model, SQLModel)), route.path


# =========================================================
# Router
# =========================================================


def test_every_inventory_route_lives_under_the_inventory_prefix():
    app_paths = {path for path in main.app.openapi()["paths"] if path.startswith("/inventory")}

    assert inventory.router.prefix == "/inventory"
    assert app_paths == {
        "/inventory/products", "/inventory/products/{sku_id}",
        "/inventory/orders", "/inventory/orders/inbound", "/inventory/orders/outbound",
    }


def test_there_is_no_route_to_edit_or_delete_stock():
    methods = {method for route in inventory.router.routes for method in route.methods}

    assert methods == {"GET", "POST"}


# =========================================================
# Supabase: la API REST no debe saltarse las reglas
# =========================================================


def test_row_level_security_closes_the_supabase_rest_api_on_every_inventory_table():
    statements = database.row_level_security_statements("postgresql")

    assert statements == [f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY" for table in ("sku", "stock_entry", "stock_exit")]
    assert set(database.INVENTORY_TABLES) == set(SQLModel.metadata.tables) & set(database.INVENTORY_TABLES)


def test_row_level_security_is_only_applied_on_postgres():
    assert database.row_level_security_statements("sqlite") == []


def test_inventory_tables_list_matches_the_orm_models():
    assert {model.__tablename__ for model in (SKU, StockEntry, StockExit)} == set(database.INVENTORY_TABLES)
