"""Tabla de almacenamiento `telemetry_events` (hito 16, Fase 1): estructura, índices, mapeo
TelemetryEvent → fila e inmutabilidad."""

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from services import database, telemetry
from services.telemetry_models import TelemetryEventRecord

ROOT = Path(__file__).resolve().parents[2]
SQL_FILE = ROOT / "infra" / "supabase" / "telemetry_events.sql"
TABLE = TelemetryEventRecord.__table__
EVENTS = json.loads((ROOT / "event-schemas.json").read_text(encoding="utf-8"))["definitions"]


def postgres_ddl() -> str:
    dialect = postgresql.dialect()
    statements = [str(CreateTable(TABLE).compile(dialect=dialect))]
    statements += [str(CreateIndex(index).compile(dialect=dialect)) for index in TABLE.indexes]
    return "\n".join(statements)


def envelope(**overrides) -> telemetry.TelemetryEvent:
    base = {
        "eventId": str(uuid.uuid4()),
        "timestamp": "2026-11-04T09:15:02.481Z",
        "sessionId": str(uuid.uuid4()),
        "userId": str(uuid.uuid4()),
        "event_type": "inbound_order_created",
        "schemaVersion": "1.0.0",
        "requestId": str(uuid.uuid4()),
        "source": "backoffice_web",
        "environment": "development",
        "properties": {
            "warehouse": "zaragoza", "country": "ES", "client_id": "glowlab_cosmetics",
            "product_id": "GLW-SRM-30", "product_category": "cosmetics", "quantity": 40,
        },
    }
    return telemetry.TelemetryEvent.model_validate({**base, **overrides})


# =========================================================
# Estructura
# =========================================================


def test_the_table_has_the_eight_columns_of_the_storage_contract():
    ddl = str(CreateTable(TABLE).compile(dialect=postgresql.dialect()))
    columns = {column.name: re.sub(r"\s+", " ", str(column.type.compile(dialect=postgresql.dialect()))) for column in TABLE.columns}

    assert columns == {
        "id": "UUID",
        "event_type": "TEXT",
        "timestamp": "TIMESTAMP WITH TIME ZONE",
        "session_id": "TEXT",
        "user_id": "TEXT",
        "source": "TEXT",
        "tags": "JSONB",
        "created_at": "TIMESTAMP WITH TIME ZONE",
    }
    assert [column.name for column in TABLE.primary_key] == ["id"]
    assert "created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL" in ddl


def test_only_session_and_user_can_be_null():
    nullable = {column.name for column in TABLE.columns if column.nullable}

    assert nullable == {"session_id", "user_id"}


def test_the_three_indexes_timestamp_event_type_and_gin_on_tags():
    indexes = {index.name: ([column.name for column in index.columns], index.dialect_options["postgresql"]["using"] or None) for index in TABLE.indexes}

    assert indexes == {
        "ix_telemetry_events_timestamp": (["timestamp"], None),
        "ix_telemetry_events_event_type": (["event_type"], None),
        "ix_telemetry_events_tags": (["tags"], "gin"),
    }
    assert "USING gin (tags)" in postgres_ddl()


def test_the_supabase_sql_script_matches_the_orm_model():
    script = re.sub(r"\s+", " ", SQL_FILE.read_text(encoding="utf-8"))

    for column in TABLE.columns:
        assert re.search(rf"\b{column.name}\b", script), column.name
    for index in TABLE.indexes:
        assert f"CREATE INDEX IF NOT EXISTS {index.name} ON telemetry_events" in script
    assert "USING gin (tags)" in script
    assert "tags JSONB NOT NULL" in script
    assert "ENABLE ROW LEVEL SECURITY" in script
    assert "BEFORE UPDATE OR DELETE ON telemetry_events" in script
    assert "BEFORE TRUNCATE ON telemetry_events" in script


# =========================================================
# Mapeo TelemetryEvent → fila
# =========================================================


def test_each_envelope_field_lands_in_its_column():
    event = envelope()

    row = telemetry.event_row(event)

    assert set(row) == {column.name for column in TABLE.columns} - {"created_at"}
    assert row["id"] == uuid.UUID(event.eventId)
    assert row["event_type"] == "inbound_order_created"
    assert row["timestamp"] == datetime(2026, 11, 4, 9, 15, 2, 481000, tzinfo=timezone.utc)
    assert (row["session_id"], row["user_id"], row["source"]) == (event.sessionId, event.userId, "backoffice_web")


def test_tags_keep_the_briefing_dimensions_and_the_envelope_fields_without_a_column():
    event = envelope()

    tags = telemetry.event_row(event)["tags"]

    assert tags == {
        "warehouse": "zaragoza", "country": "ES", "client_id": "glowlab_cosmetics",
        "product_id": "GLW-SRM-30", "product_category": "cosmetics", "quantity": 40,
        "environment": "development", "schema_version": "1.0.0", "request_id": event.requestId,
    }


def test_null_properties_are_kept_as_null_tags_not_dropped():
    event = envelope(event_type="page_viewed", properties={"page_route": "/", "section": "dashboard", "previous_route": None})

    assert telemetry.event_row(event)["tags"]["previous_route"] is None


def test_no_event_of_the_catalogue_uses_the_tag_names_reserved_for_the_envelope():
    reserved = {"environment", "schema_version", "request_id"}

    for name, schema in EVENTS.items():
        if name == "envelope":
            continue
        properties = schema["properties"]["properties"].get("properties", {})
        assert not reserved & set(properties), name


def test_an_event_without_session_or_user_maps_to_null_columns():
    row = telemetry.event_row(envelope(sessionId=None, userId=None, source="api"))

    assert (row["session_id"], row["user_id"]) == (None, None)


# =========================================================
# Inmutabilidad
# =========================================================


def test_postgres_rejects_update_delete_and_truncate_with_a_trigger():
    statements = " ".join(database.telemetry_immutability_statements("postgresql"))

    assert "BEFORE UPDATE OR DELETE ON telemetry_events FOR EACH ROW" in statements
    assert "BEFORE TRUNCATE ON telemetry_events FOR EACH STATEMENT" in statements
    assert "RAISE EXCEPTION" in statements
    # psycopg tomaría un '%' suelto por un parámetro.
    assert "%" not in statements


def test_the_trigger_is_only_installed_on_postgres():
    assert database.telemetry_immutability_statements("sqlite") == []


def test_row_level_security_also_closes_the_rest_api_on_the_telemetry_table():
    assert "ALTER TABLE telemetry_events ENABLE ROW LEVEL SECURITY" in database.row_level_security_statements("postgresql")


@pytest.mark.parametrize("path", ["services/telemetry/__init__.py", "services/telemetry/analysis.py", "services/telemetry_models.py", "services/routers/telemetry.py"])
def test_the_telemetry_code_never_updates_or_deletes_events(path):
    source = (ROOT / path).read_text(encoding="utf-8")

    assert not re.search(r"\b(update|delete)\s*\(", source)
    assert not re.search(r"session\.(delete|merge)\b", source)
    assert not re.search(r"\b(UPDATE|DELETE FROM)\s+telemetry_events", source)
