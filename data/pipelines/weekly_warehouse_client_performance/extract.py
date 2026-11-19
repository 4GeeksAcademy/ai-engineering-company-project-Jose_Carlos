"""Etapa 1 — Extracción (PIPELINE_DESIGN.md §4 y §6.2).

Lee `public.telemetry_events` **en solo lectura**: aquí solo hay `SELECT`. Nunca se trae `tags`
entero: los campos que usa el pipeline se proyectan en la propia consulta (`tags->>'warehouse'`
en PostgreSQL, `JSON_EXTRACT` en SQLite).

- `resolve_weeks()` decide qué semanas recalcular: la semana ISO recién cerrada, `lookback_weeks`
  anteriores y las semanas con llegadas tardías (eventos con `created_at` posterior a la marca de
  agua de la última corrida correcta).
- `extract_inventory_events()` trae los eventos de esas semanas, de los cuatro tipos de origen, del
  `environment` pedido y con `created_at <= extracted_until` (el corte fijo de la corrida).
"""

from datetime import date, datetime, timedelta

import pandas as pd
from sqlalchemy import select
from sqlalchemy.engine import Engine

from services.telemetry_models import TelemetryEventRecord

from . import config

TABLE = TelemetryEventRecord.__table__

EVENT_COLUMNS = [
    "event_id", "event_type", "timestamp", "created_at", "warehouse", "client_id", "quantity", "business_key",
]
_ID_COLUMNS = list(config.BUSINESS_KEY_FIELDS.values())


def _base_filter(statement, environment: str, extracted_until: datetime):
    return statement.where(
        TABLE.c.event_type.in_(config.SOURCE_EVENT_TYPES),
        TABLE.c.tags["environment"].as_string() == environment,
        TABLE.c.created_at <= extracted_until,
    )


def resolve_weeks(
    engine: Engine,
    *,
    as_of: datetime,
    extracted_until: datetime,
    environment: str,
    week_start: date | None = None,
    lookback_weeks: int = config.DEFAULT_LOOKBACK_WEEKS,
    last_watermark: datetime | None = None,
    include_late_arrivals: bool = True,
) -> list[date]:
    """Semanas (lunes) a recalcular, de la más antigua a la más reciente.

    Sin marca de agua (primera corrida) cuentan como «tardíos» todos los eventos: la primera
    corrida reconstruye el histórico completo. Nunca se incluye una semana posterior a la pedida
    (la semana en curso no está cerrada).
    """
    if week_start is not None and week_start.weekday() != 0:
        raise ValueError(f"week_start debe ser lunes: {week_start.isoformat()}")
    if not 0 <= lookback_weeks <= config.MAX_LOOKBACK_WEEKS:
        raise ValueError(f"lookback_weeks debe estar entre 0 y {config.MAX_LOOKBACK_WEEKS}")

    target = week_start or config.last_closed_week(as_of)
    weeks = {target - timedelta(weeks=offset) for offset in range(lookback_weeks + 1)}

    if include_late_arrivals:
        statement = _base_filter(select(TABLE.c.timestamp), environment, extracted_until)
        if last_watermark is not None:
            statement = statement.where(TABLE.c.created_at > last_watermark)
        with engine.connect() as connection:
            timestamps = pd.Series(connection.execute(statement).scalars().all(), dtype=object)
        if not timestamps.empty:
            days = pd.to_datetime(timestamps, utc=True, format="ISO8601").dt.date
            weeks |= {config.week_monday(day) for day in days.unique()}

    return sorted(week for week in weeks if week <= target)


def extract_inventory_events(
    engine: Engine, weeks: list[date], extracted_until: datetime, environment: str
) -> pd.DataFrame:
    """Eventos de origen de las semanas pedidas, con las columnas de PIPELINE_DESIGN.md §4.2.

    Una sola consulta con la ventana `[lunes más antiguo, lunes siguiente al más reciente)`; las
    semanas intermedias que no se pidieron las descarta la transformación.
    """
    if not weeks:
        return pd.DataFrame(columns=EVENT_COLUMNS)
    window_start, _ = config.week_bounds(min(weeks))
    _, window_end = config.week_bounds(max(weeks))

    statement = _base_filter(
        select(
            TABLE.c.id.label("event_id"),
            TABLE.c.event_type,
            TABLE.c.timestamp,
            TABLE.c.created_at,
            TABLE.c.tags["warehouse"].as_string().label("warehouse"),
            TABLE.c.tags["client_id"].as_string().label("client_id"),
            TABLE.c.tags["quantity"].as_integer().label("quantity"),
            *(TABLE.c.tags[field].as_integer().label(field) for field in _ID_COLUMNS),
        ),
        environment,
        extracted_until,
    ).where(TABLE.c.timestamp >= window_start, TABLE.c.timestamp < window_end)

    with engine.connect() as connection:
        rows = connection.execute(statement).mappings().all()
    df = pd.DataFrame(rows, columns=[*EVENT_COLUMNS[:-1], *_ID_COLUMNS])
    if df.empty:
        return pd.DataFrame(columns=EVENT_COLUMNS)

    # El id de dominio del movimiento: cada evento lleva solo el suyo (BUSINESS_KEY_FIELDS).
    ids = df[_ID_COLUMNS].apply(pd.to_numeric, errors="coerce").bfill(axis=1).iloc[:, 0]
    df["business_key"] = ids.astype("Int64").astype("string")
    df["event_id"] = df["event_id"].astype(str)
    return df[EVENT_COLUMNS]
