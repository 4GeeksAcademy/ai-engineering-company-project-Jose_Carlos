"""Etapa 3 — Carga en `reporting.weekly_warehouse_client_performance` (PIPELINE_DESIGN.md §6.1 y §8).

UPSERT por el constraint `unique (warehouse, client_id, week_start)` del BRIEFING §5: si la fila
existe se sobrescribe con los totales recalculados; si no, se crea. Nunca hay incrementos
(`count = count + …`), así que repetir la carga con el mismo DataFrame deja la tabla igual.
"""

import uuid
from datetime import date, datetime
from typing import NamedTuple

import pandas as pd
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.engine import Connection, Engine

from . import config
from .schema import weekly_warehouse_client_performance as TARGET


class LoadResult(NamedTuple):
    rows_upserted: int
    rows_deleted: int


def _insert(dialect_name: str):
    if dialect_name == "postgresql":
        return postgresql.insert(TARGET)
    if dialect_name == "sqlite":
        return sqlite.insert(TARGET)
    raise RuntimeError(f"UPSERT no soportado para el dialecto {dialect_name}")


def _rows(weekly: pd.DataFrame, computed_at: datetime) -> list[dict]:
    records = weekly.to_dict(orient="records")
    return [
        {
            "id": uuid.uuid4(),  # solo se usa si la fila es nueva: un UPDATE conserva el id existente
            "warehouse": row["warehouse"],
            "client_id": row["client_id"],
            "week_start": row["week_start"],
            **{column: int(row[column]) for column in config.KPI_COLUMNS[:-1]},
            "discrepancy_rate": float(row["discrepancy_rate"]),
            "computed_at": computed_at,
        }
        for row in records
    ]


def upsert_rows(connection: Connection, weekly: pd.DataFrame, computed_at: datetime) -> int:
    """INSERT … ON CONFLICT (warehouse, client_id, week_start) DO UPDATE, en un único executemany."""
    rows = _rows(weekly, computed_at)
    if not rows:
        return 0
    statement = _insert(connection.dialect.name)
    statement = statement.on_conflict_do_update(
        index_elements=list(config.KEY_COLUMNS),
        set_={column: statement.excluded[column] for column in (*config.KPI_COLUMNS, "computed_at")},
    )
    connection.execute(statement, rows)
    return len(rows)


def load_weekly_performance(
    engine: Engine, weekly: pd.DataFrame, weeks: list[date], computed_at: datetime
) -> LoadResult:
    """Carga el DataFrame semanal en una transacción: o entran todas las filas o ninguna."""
    with engine.begin() as connection:
        upserted = upsert_rows(connection, weekly, computed_at)
    return LoadResult(rows_upserted=upserted, rows_deleted=0)
