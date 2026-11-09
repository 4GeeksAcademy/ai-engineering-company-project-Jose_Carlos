"""Tablas del esquema `reporting` (PIPELINE_DESIGN.md §7 y §9).

- En PostgreSQL (Supabase) la fuente de verdad del DDL es `sql/001_reporting_schema.sql`, con la
  tabla del BRIEFING §5 tal cual (`default gen_random_uuid()`, `unique (warehouse, client_id,
  week_start)`). `ensure_reporting_schema()` la ejecuta: es idempotente.
- En SQLite (tests) no hay esquemas: el motor adjunta una base `reporting` (ver
  `connections.attach_reporting_schema`) y las tablas se crean desde estas definiciones.

Estas tablas usan su propio `MetaData`, así que `services/database.create_db_and_tables` (que crea
`SQLModel.metadata`) nunca las toca, y este pipeline nunca crea ni altera `telemetry_events`.
"""

from pathlib import Path

from sqlalchemy import (
    JSON, CheckConstraint, Column, Date, DateTime, Index, Integer, MetaData, Numeric, Table, Text,
    UniqueConstraint, Uuid, text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine

SCHEMA = "reporting"
SQL_DIR = Path(__file__).resolve().parent / "sql"
SCHEMA_SQL = SQL_DIR / "001_reporting_schema.sql"

metadata = MetaData(schema=SCHEMA)

weekly_warehouse_client_performance = Table(
    "weekly_warehouse_client_performance",
    metadata,
    # El id lo genera la aplicación (uuid4) para que el mismo INSERT valga en PostgreSQL y SQLite;
    # en PostgreSQL la columna tiene además `default gen_random_uuid()` (DDL del BRIEFING). Un
    # UPSERT que actualiza nunca lo cambia.
    Column("id", Uuid, primary_key=True),
    Column("warehouse", Text, nullable=False),
    Column("client_id", Text, nullable=False),
    Column("week_start", Date, nullable=False),
    Column("inbound_units_count", Integer, nullable=False, default=0),
    Column("outbound_orders_count", Integer, nullable=False, default=0),
    Column("stockout_events_count", Integer, nullable=False, default=0),
    Column("discrepancy_events_count", Integer, nullable=False, default=0),
    Column("discrepancy_rate", Numeric(asdecimal=False), nullable=False, default=0),
    Column("computed_at", DateTime(timezone=True), nullable=False),
    # El constraint en el que se apoya el UPSERT (BRIEFING §5, PIPELINE_DESIGN.md §6.1).
    # (El UPSERT lo referencia por columnas, no por nombre: en PostgreSQL el nombre lo pone la base.)
    UniqueConstraint("warehouse", "client_id", "week_start", name="uq_wwcp_warehouse_client_week"),
    Index("ix_wwcp_week_start", "week_start"),
)

RUN_STATUSES = ("running", "completed", "failed")
RUN_TRIGGERS = ("scheduled", "manual", "backfill")
ERROR_STAGES = ("start", "extract", "transform", "load", "crashed")

JsonType = JSON().with_variant(JSONB(), "postgresql")

# Log de ejecución y tabla de control de la marca de agua (PIPELINE_DESIGN.md §9).
pipeline_runs = Table(
    "pipeline_runs",
    metadata,
    Column("run_id", Uuid, primary_key=True),               # = id del flow run de Prefect
    Column("pipeline_name", Text, nullable=False),
    Column("trigger", Text, nullable=False),
    Column("triggered_by", Text),
    Column("status", Text, nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("finished_at", DateTime(timezone=True)),
    Column("weeks_processed", JsonType, nullable=False, default=list),  # lista de lunes ISO
    Column("source_watermark", DateTime(timezone=True), nullable=False),  # = extracted_until
    Column("events_extracted", Integer, nullable=False, default=0),
    Column("events_discarded", Integer, nullable=False, default=0),
    Column("events_deduplicated", Integer, nullable=False, default=0),
    Column("rows_upserted", Integer, nullable=False, default=0),
    Column("rows_deleted", Integer, nullable=False, default=0),
    Column("error_stage", Text),
    Column("error_message", Text),
    Column("warnings", JsonType, nullable=False, default=list),       # fallos de pasos opcionales
    Column("parameters", JsonType, nullable=False, default=dict),
    Column("code_version", Text),
    CheckConstraint(f"status in {RUN_STATUSES}", name="ck_pipeline_runs_status"),
    CheckConstraint(f"trigger in {RUN_TRIGGERS}", name="ck_pipeline_runs_trigger"),
    CheckConstraint("status = 'running' or finished_at is not null", name="ck_pipeline_runs_finished"),
    CheckConstraint("status <> 'failed' or error_stage is not null", name="ck_pipeline_runs_error_stage"),
    # Como mucho una corrida en curso por pipeline: un segundo `running` falla al insertarse.
    Index("ux_pipeline_runs_one_running", "pipeline_name", unique=True,
          sqlite_where=text("status = 'running'"), postgresql_where=text("status = 'running'")),
    Index("ix_pipeline_runs_latest", "pipeline_name", "started_at"),
)


def ensure_reporting_schema(engine: Engine) -> None:
    """Crea el esquema `reporting` y sus tablas si no existen. Nunca borra ni altera datos."""
    if engine.dialect.name == "postgresql":
        # psycopg 3 acepta varias sentencias en una ejecución sin parámetros (incluidos bloques DO).
        with engine.begin() as connection:
            connection.exec_driver_sql(SCHEMA_SQL.read_text(encoding="utf-8"))
    else:
        metadata.create_all(engine, checkfirst=True)
