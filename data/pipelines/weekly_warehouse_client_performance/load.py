"""Etapa 3 — Carga idempotente en `reporting.weekly_warehouse_client_performance` (PIPELINE_DESIGN.md §6.1, §6.4 y §8).

Toda la carga de una corrida es **una sola transacción**:

1. `pg_advisory_xact_lock`: como mucho una carga de este pipeline a la vez (en PostgreSQL; se
   libera solo con el COMMIT o el ROLLBACK, también si el proceso muere).
2. UPSERT por el constraint `unique (warehouse, client_id, week_start)` del BRIEFING §5: si la
   fila existe se sobrescribe con los totales recalculados; si no, se crea.
3. Reemplazo por semana: se borran las filas de las semanas procesadas cuyo par
   `(warehouse, client_id)` ya no produce el cálculo (solo pasa tras un cambio de lógica).

Por qué es idempotente: los valores son **totales absolutos** de semanas completas, nunca
incrementos (`count = count + …`). Cargar dos veces el mismo DataFrame deja la tabla igual (solo
cambia `computed_at`). Si la transacción falla a mitad, PostgreSQL la deshace entera y la tabla
queda como antes de la corrida; la siguiente corrida recalcula las mismas semanas y escribe lo
mismo que habría escrito la que falló.
"""

import uuid
from datetime import date, datetime
from typing import NamedTuple

import pandas as pd
from sqlalchemy import delete, select, text
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.engine import Connection, Engine

from . import config
from .schema import weekly_warehouse_client_performance as TARGET

LOCK_KEY = f"reporting.{config.PIPELINE_NAME}"


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


def lock(connection: Connection) -> None:
    """Candado de transacción: serializa dos cargas simultáneas del pipeline (PostgreSQL)."""
    if connection.dialect.name == "postgresql":
        connection.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": LOCK_KEY})


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


def delete_orphans(connection: Connection, weekly: pd.DataFrame, weeks: list[date]) -> int:
    """Borra las filas de `weeks` que no están en el nuevo resultado (reemplazo por semana)."""
    if not weeks:
        return 0
    existing = connection.execute(
        select(TARGET.c.id, TARGET.c.warehouse, TARGET.c.client_id, TARGET.c.week_start)
        .where(TARGET.c.week_start.in_(weeks))
    ).all()
    current = set(weekly[list(config.KEY_COLUMNS)].itertuples(index=False, name=None))
    orphans = [row.id for row in existing if (row.warehouse, row.client_id, row.week_start) not in current]
    if orphans:
        connection.execute(delete(TARGET).where(TARGET.c.id.in_(orphans)))
    return len(orphans)


def load_weekly_performance(
    engine: Engine, weekly: pd.DataFrame, weeks: list[date], computed_at: datetime
) -> LoadResult:
    """Carga el DataFrame semanal en UNA transacción: o entran todas las filas o ninguna."""
    with engine.begin() as connection:
        lock(connection)
        upserted = upsert_rows(connection, weekly, computed_at)
        deleted = delete_orphans(connection, weekly, weeks)
    return LoadResult(rows_upserted=upserted, rows_deleted=deleted)
