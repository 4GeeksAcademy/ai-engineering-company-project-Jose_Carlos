"""Fixtures del pipeline de desempeño de negocio (hito 19).

`reporting_db` es un SQLite en memoria con todo lo que toca el pipeline: `telemetry_events`
(fuente), `sku` y `stock_exit` (conciliación opcional) y el esquema `reporting` adjunto
(destino). Sustituye los motores del pipeline y de la API: nunca se toca el Supabase del `.env`.
"""

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import insert
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, create_engine

from data.pipelines.weekly_warehouse_client_performance import connections, schema
from services import telemetry
from services.models import SKU, StockExit
from services.telemetry_models import TelemetryEventRecord

ENVIRONMENT = "test"

# Semana de referencia: lunes 2 de noviembre de 2026; la corrida programada es el lunes 9 a las 06:00.
WEEK = date(2026, 11, 2)
PREVIOUS_WEEK = date(2026, 10, 26)
AS_OF = datetime(2026, 11, 9, 6, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def prefect_server(tmp_path_factory):
    """Servidor de Prefect temporal para los tests que corren flows.

    Los resultados persistidos (la caché de la transformación) van a un directorio desechable,
    nunca a ~/.prefect/storage.
    """
    from prefect.settings import PREFECT_LOCAL_STORAGE_PATH, temporary_settings
    from prefect.testing.utilities import prefect_test_harness

    storage = tmp_path_factory.mktemp("prefect-storage")
    with temporary_settings({PREFECT_LOCAL_STORAGE_PATH: storage}):
        with prefect_test_harness(server_startup_timeout=120):
            yield


@pytest.fixture
def reporting_db(monkeypatch, tmp_path):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    connections.attach_reporting_schema(engine)
    TelemetryEventRecord.__table__.create(engine)
    SKU.__table__.create(engine)
    StockExit.__table__.create(engine)
    schema.ensure_reporting_schema(engine)

    monkeypatch.setattr(telemetry, "open_session", lambda: Session(engine))
    monkeypatch.setattr(connections, "reader_engine", lambda: engine)
    monkeypatch.setattr(connections, "writer_engine", lambda: engine)
    monkeypatch.setattr(connections, "api_engine", lambda: engine)
    monkeypatch.setenv(connections.ENVIRONMENT_ENV, ENVIRONMENT)
    monkeypatch.setenv("REPORTING_SNAPSHOT_DIR", str(tmp_path / "snapshots"))
    yield engine
    engine.dispose()


_ids = iter(range(1, 1_000_000))


def inventory_event(
    event_type: str,
    timestamp: str,
    *,
    warehouse: str = "los_angeles",
    client_id: str = "purestep_footwear",
    quantity: int = 1,
    business_id: int | None = None,
    environment: str = ENVIRONMENT,
) -> telemetry.TelemetryEvent:
    """Un evento de origen válido según su allowlist de event-schemas.json."""
    base = {
        "warehouse": warehouse,
        "country": "US" if warehouse == "los_angeles" else "ES",
        "client_id": client_id,
        "product_id": "CLT-SNK-W-42",
        "product_category": "fashion",
        "quantity": quantity,
    }
    business_id = business_id if business_id is not None else next(_ids)
    extra = {
        "inbound_order_created": {"inbound_order_id": business_id, "stock_after": 100},
        "outbound_order_created": {"outbound_order_id": business_id, "stock_after": 10},
        "stock_threshold_triggered": {
            "min_stock": 10, "stock_before": 12, "trigger_order_type": "dispatch", "trigger_order_id": business_id,
        },
        "inventory_discrepancy_detected": {
            "system_quantity": 10, "counted_quantity": 10 - quantity, "difference": -quantity,
            "count_type": "cycle_count", "count_id": business_id,
        },
    }[event_type]
    source = "api" if event_type in ("stock_threshold_triggered", "inventory_discrepancy_detected") else "backoffice_web"
    return telemetry.TelemetryEvent(
        eventId=str(uuid.uuid4()),
        timestamp=timestamp,
        sessionId=None,
        userId=None,
        event_type=event_type,
        schemaVersion="1.0.0",
        requestId=str(uuid.uuid4()),
        source=source,
        environment=environment,
        properties={**base, **extra},
    )


def store(engine, *events: telemetry.TelemetryEvent, ingested_at: datetime | None = None) -> None:
    """Guarda eventos con un `created_at` controlado (por defecto, 5 s después de su timestamp)."""
    rows = []
    for event in events:
        row = telemetry.event_row(event)
        row["created_at"] = ingested_at or row["timestamp"] + timedelta(seconds=5)
        rows.append(row)
    with engine.begin() as connection:
        connection.execute(insert(TelemetryEventRecord.__table__), rows)


@pytest.fixture
def week_of_activity(reporting_db):
    """Una semana (2026-11-02) con actividad de dos clientes en los dos almacenes.

    los_angeles × purestep_footwear: 2 entradas (300 + 120 u.), 4 despachos, 1 quiebre, 1 discrepancia
    zaragoza    × purestep_footwear: 1 entrada (50 u.), 0 despachos, 0 quiebres, 1 discrepancia
    los_angeles × glowlab_cosmetics: 1 entrada (80 u.), 2 despachos
    """
    la, zgz = "los_angeles", "zaragoza"
    store(
        reporting_db,
        inventory_event("inbound_order_created", "2026-11-02T08:00:00.000Z", warehouse=la, quantity=300),
        inventory_event("inbound_order_created", "2026-11-05T10:00:00.000Z", warehouse=la, quantity=120),
        *(inventory_event("outbound_order_created", f"2026-11-0{day}T12:00:00.000Z", warehouse=la) for day in (3, 4, 6, 7)),
        inventory_event("stock_threshold_triggered", "2026-11-06T12:00:01.000Z", warehouse=la, quantity=4),
        inventory_event("inventory_discrepancy_detected", "2026-11-07T09:00:00.000Z", warehouse=la, quantity=2),
        inventory_event("inbound_order_created", "2026-11-03T08:00:00.000Z", warehouse=zgz, quantity=50),
        inventory_event("inventory_discrepancy_detected", "2026-11-04T09:00:00.000Z", warehouse=zgz, quantity=1),
        inventory_event("inbound_order_created", "2026-11-04T08:00:00.000Z", warehouse=la,
                        client_id="glowlab_cosmetics", quantity=80),
        *(inventory_event("outbound_order_created", f"2026-11-0{day}T15:00:00.000Z", warehouse=la,
                          client_id="glowlab_cosmetics") for day in (5, 8)),
    )
    return reporting_db
