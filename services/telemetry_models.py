"""Tabla de almacenamiento de la telemetría en Supabase: `telemetry_events` (hito 16).

Una fila por evento aceptado, venga del backoffice o de la propia API. Es la tabla, no el
contrato: el contrato sigue siendo `services.telemetry.TelemetryEvent`, y
`services.telemetry.event_row()` traduce cada evento validado a una fila:

    TelemetryEvent           telemetry_events
    ----------------------   --------------------------------------------------
    eventId               →  id            uuid PK (clave de idempotencia)
    event_type            →  event_type    text
    timestamp             →  timestamp     timestamptz (momento de la captura)
    sessionId             →  session_id    text, nullable
    userId                →  user_id       text, nullable
    source                →  source        text (api | backoffice_web)
    properties            →  tags          jsonb, tal cual (allowlist de event-schemas.json)
    environment           →  tags.environment
    schemaVersion         →  tags.schema_version
    requestId             →  tags.request_id
    (lo pone la base)        created_at    timestamptz DEFAULT now() (momento de la ingesta)

- Tres índices para consultar a escala: `timestamp` (rangos de fechas), `event_type` (un
  evento concreto) y GIN sobre `tags` (búsquedas dentro del JSONB: almacén, cliente, país…).
- Inmutable: la API solo hace INSERT. En PostgreSQL, además, un trigger rechaza cualquier
  UPDATE, DELETE o TRUNCATE (services/database.py, `telemetry_immutability_statements`).
- En SQLite (tests y suite de navegador) `JSONB` cae a `JSON` y el índice GIN a uno normal.
"""

import uuid
from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, Column, DateTime, Index, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


TELEMETRY_TABLE = "telemetry_events"
SOURCES = ("api", "backoffice_web")

# JSONB en Supabase; JSON en SQLite.
TagsType = JSON().with_variant(JSONB(), "postgresql")


class TelemetryEventRecord(SQLModel, table=True):
    """Un evento de telemetría ya validado. Nunca se actualiza ni se borra."""

    __tablename__ = TELEMETRY_TABLE
    __table_args__ = (
        CheckConstraint("source IN ('api', 'backoffice_web')", name="ck_telemetry_events_source"),
        Index("ix_telemetry_events_timestamp", "timestamp"),
        Index("ix_telemetry_events_event_type", "event_type"),
        Index("ix_telemetry_events_tags", "tags", postgresql_using="gin"),
    )

    # El eventId del navegador o de la API: un reintento del mismo lote no duplica filas.
    id: uuid.UUID = Field(primary_key=True)
    event_type: str = Field(sa_type=Text, nullable=False)
    timestamp: datetime = Field(sa_type=DateTime(timezone=True), nullable=False)
    session_id: str | None = Field(default=None, sa_type=Text)
    user_id: str | None = Field(default=None, sa_type=Text)
    source: str = Field(sa_type=Text, nullable=False)
    tags: dict = Field(sa_column=Column(TagsType, nullable=False))
    created_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    )
