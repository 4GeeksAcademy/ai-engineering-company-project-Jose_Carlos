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
    Column, Date, DateTime, Index, Integer, MetaData, Numeric, Table, Text, UniqueConstraint, Uuid,
)
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


def ensure_reporting_schema(engine: Engine) -> None:
    """Crea el esquema `reporting` y sus tablas si no existen. Nunca borra ni altera datos."""
    if engine.dialect.name == "postgresql":
        # psycopg 3 acepta varias sentencias en una ejecución sin parámetros (incluidos bloques DO).
        with engine.begin() as connection:
            connection.exec_driver_sql(SCHEMA_SQL.read_text(encoding="utf-8"))
    else:
        metadata.create_all(engine, checkfirst=True)
