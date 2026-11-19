"""Lecturas del esquema `reporting` para services/reporting/ (PIPELINE_DESIGN.md §11). Sin ETL.

`get_weekly_performance()` devuelve el contrato del BRIEFING §6: la semana y todas sus combinaciones
almacén/cliente con los cuatro KPIs. Lo consume GET /reporting/weekly-warehouse-client-performance
(el feed del dashboard ejecutivo de la Parte 3).
"""

from datetime import date
from typing import Any

from sqlalchemy import func, inspect, select
from sqlalchemy.engine import Engine

from . import config
from .schema import SCHEMA
from .schema import pipeline_runs as RUNS
from .schema import weekly_warehouse_client_performance as TARGET

ENTRY_COLUMNS = ("warehouse", "client_id", *config.KPI_COLUMNS)


def reporting_ready(engine: Engine) -> bool:
    """Si el pipeline aún no ha corrido nunca, las tablas de `reporting` no existen."""
    inspector = inspect(engine)
    return inspector.has_table(TARGET.name, schema=SCHEMA) and inspector.has_table(RUNS.name, schema=SCHEMA)


def latest_computed_week(engine: Engine) -> date | None:
    with engine.connect() as connection:
        return connection.execute(select(func.max(TARGET.c.week_start))).scalar_one_or_none()


def _iso(moment) -> str | None:
    if moment is None:
        return None
    if isinstance(moment, str):  # SQLite puede devolver el texto guardado
        return moment
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=config.utc_now().tzinfo)
    return moment.isoformat(timespec="seconds").replace("+00:00", "Z")


def get_weekly_performance(engine: Engine, week_start: date | None = None) -> dict[str, Any] | None:
    """`{week_start, computed_at, entries: [...]}` de la semana pedida (por defecto, la más
    reciente calculada); None si no hay filas."""
    if not reporting_ready(engine):
        return None
    week = week_start or latest_computed_week(engine)
    if week is None:
        return None
    with engine.connect() as connection:
        rows = connection.execute(
            select(*(TARGET.c[name] for name in ENTRY_COLUMNS), TARGET.c.computed_at)
            .where(TARGET.c.week_start == week)
            .order_by(TARGET.c.warehouse, TARGET.c.client_id)
        ).all()
    if not rows:
        return None
    entries = [
        {
            "warehouse": row.warehouse,
            "client_id": row.client_id,
            **{name: int(getattr(row, name)) for name in config.KPI_COLUMNS[:-1]},
            "discrepancy_rate": float(row.discrepancy_rate),
        }
        for row in rows
    ]
    computed = [row.computed_at for row in rows if row.computed_at is not None]
    return {"week_start": week.isoformat(), "computed_at": _iso(max(computed)) if computed else None, "entries": entries}
