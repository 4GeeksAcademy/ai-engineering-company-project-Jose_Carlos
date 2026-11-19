"""Dead Letter Queue de la cola de tareas: la tabla `task_dead_letters` (hito 22, ticket #DEV-55).

Cuando una tarea agota sus reintentos, el worker la registra aquí con su `task_id`, el intento en
el que falló, el error completo y la hora (`TrackedTask.on_failure`). Es una tabla, no una cola de
Redis: el ticket pide que el fallo quede en base de datos, y así sobrevive a que Redis expire los
resultados (24 h) y se puede consultar con SQL.

- En PostgreSQL (Supabase) la fuente de verdad del DDL es `sql/001_task_dead_letters.sql`.
- En SQLite (tests) la tabla se crea desde esta definición.

Base de datos: `TASKS_DATABASE_URL` o, si no está, `DATABASE_URL` (la de la API).
"""

import json
import os
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy import (
    JSON, CheckConstraint, Column, DateTime, Index, Integer, MetaData, Table, Text, Uuid, insert, select,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from services.job_runner.db import DatabaseNotConfigured, database_url, make_engine

SCHEMA_SQL = Path(__file__).resolve().parent / "sql" / "001_task_dead_letters.sql"
URL_ENV = "TASKS_DATABASE_URL"

JsonType = JSON().with_variant(JSONB(), "postgresql")

metadata = MetaData()

task_dead_letters = Table(
    "task_dead_letters",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("task_id", Text, nullable=False),
    Column("task_name", Text, nullable=False),
    Column("attempt", Integer, nullable=False),
    Column("max_retries", Integer),
    Column("error_type", Text, nullable=False),
    Column("error_message", Text, nullable=False),
    Column("args", JsonType, nullable=False, default=list),
    Column("kwargs", JsonType, nullable=False, default=dict),
    Column("queue", Text),
    Column("worker", Text),
    Column("failed_at", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("attempt >= 1", name="ck_task_dead_letters_attempt"),
    Index("ux_task_dead_letters_task_id", "task_id", unique=True),
    Index("ix_task_dead_letters_failed_at", "failed_at"),
)


@lru_cache(maxsize=1)
def dead_letter_engine() -> Engine:
    """Motor de la DLQ (uno por proceso del worker)."""
    if url := os.getenv(URL_ENV, "").strip():
        return make_engine(url)
    return make_engine(database_url())


def ensure_dead_letter_table(engine: Engine) -> None:
    """Crea `task_dead_letters` y sus índices si no existen. Nunca borra ni altera datos."""
    if engine.dialect.name == "postgresql":
        with engine.begin() as connection:
            connection.exec_driver_sql(SCHEMA_SQL.read_text(encoding="utf-8"))
    else:
        metadata.create_all(engine, checkfirst=True)


def _json_safe(value: Any) -> Any:
    """Los argumentos ya llegaron por JSON; esto solo protege de un valor raro en kwargs."""
    return json.loads(json.dumps(value, default=str))


def record_dead_letter(
    engine: Engine,
    *,
    task_id: str,
    task_name: str,
    attempt: int,
    max_retries: int | None,
    error: BaseException,
    error_message: str,
    args: list | tuple | None = None,
    kwargs: dict | None = None,
    queue: str | None = None,
    worker: str | None = None,
    failed_at: datetime | None = None,
) -> bool:
    """Registra la tarea en la DLQ. Devuelve False si ya estaba (misma `task_id`)."""
    ensure_dead_letter_table(engine)
    now = datetime.now(timezone.utc)
    row = {
        "id": uuid.uuid4(),
        "task_id": task_id,
        "task_name": task_name,
        "attempt": attempt,
        "max_retries": max_retries,
        "error_type": type(error).__name__,
        "error_message": error_message,
        "args": _json_safe(list(args or [])),
        "kwargs": _json_safe(dict(kwargs or {})),
        "queue": queue,
        "worker": worker,
        "failed_at": failed_at or now,
        "created_at": now,
    }
    try:
        with engine.begin() as connection:
            connection.execute(insert(task_dead_letters), row)
    except IntegrityError:
        return False
    return True


def get_dead_letter(engine: Engine, task_id: str) -> dict | None:
    with engine.connect() as connection:
        row = connection.execute(select(task_dead_letters).where(task_dead_letters.c.task_id == task_id)).mappings().first()
    return dict(row) if row else None


def list_dead_letters(engine: Engine, limit: int = 50) -> list[dict]:
    query = select(task_dead_letters).order_by(task_dead_letters.c.failed_at.desc()).limit(limit)
    with engine.connect() as connection:
        return [dict(row) for row in connection.execute(query).mappings()]


__all__ = [
    "DatabaseNotConfigured", "dead_letter_engine", "ensure_dead_letter_table", "get_dead_letter",
    "list_dead_letters", "record_dead_letter", "task_dead_letters",
]
