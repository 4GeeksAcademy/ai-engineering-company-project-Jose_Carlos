"""Conexiones del pipeline (PIPELINE_DESIGN.md §10.5).

Dos motores con responsabilidades distintas:

- `reader_engine()`: lee `public.telemetry_events` (y `stock_exit`/`sku` para la conciliación
  opcional). En producción, con el rol `reporting_reader`, que solo tiene SELECT.
- `writer_engine()`: escribe en el esquema `reporting`. En producción, con el rol
  `reporting_writer`, sin permisos en `public`.

Orden para resolver cada URL:

1. Block `Secret` de Prefect (`supabase-telemetry-reader-url` / `supabase-reporting-writer-url`):
   la configuración de producción, cifrada por Prefect.
2. Variable de entorno (`REPORTING_READER_DATABASE_URL` / `REPORTING_WRITER_DATABASE_URL`).
3. `DATABASE_URL` de la API (services/api/config.py): en local, los dos motores usan la misma
   conexión; la garantía de solo lectura la da entonces el código (ninguna sentencia del
   pipeline escribe en `telemetry_events`) y el trigger de inmutabilidad del hito 16.

`api_engine()` es el motor de la API (services/database.py), con el que services/reporting/ lee
las tablas de `reporting`.
"""

import logging
import os
from functools import lru_cache

from sqlalchemy import event
from sqlalchemy.engine import Engine, make_url
from sqlmodel import create_engine

logger = logging.getLogger("pipelines.weekly_warehouse_client_performance")

READER_BLOCK = "supabase-telemetry-reader-url"
WRITER_BLOCK = "supabase-reporting-writer-url"
READER_ENV = "REPORTING_READER_DATABASE_URL"
WRITER_ENV = "REPORTING_WRITER_DATABASE_URL"


def attach_reporting_schema(engine: Engine, database: str = ":memory:") -> None:
    """SQLite no tiene esquemas: adjunta una base llamada `reporting` en cada conexión nueva."""

    @event.listens_for(engine, "connect")
    def _attach(dbapi_connection, _record):
        dbapi_connection.execute(f"ATTACH DATABASE '{database}' AS reporting")


def _secret_block(name: str) -> str | None:
    """Valor del block Secret `name`, o None si Prefect no está disponible o no existe."""
    try:
        from prefect.blocks.system import Secret

        return Secret.load(name, _sync=True).get()
    except Exception:  # noqa: BLE001 - sin servidor, sin block o sin Prefect: se usa el siguiente origen
        return None


def _api_database_url() -> str:
    from services import database

    return database.DATABASE_URL


def resolve_url(block: str, env: str) -> str:
    return _secret_block(block) or os.getenv(env, "").strip() or _api_database_url()


@lru_cache(maxsize=8)
def engine_for(url: str) -> Engine:
    """Un motor por URL (se reutiliza entre corridas del mismo proceso)."""
    from services import database

    url = database._engine_url(url)  # postgres(ql):// → postgresql+psycopg://, como la API
    parsed = make_url(url)
    if parsed.drivername.startswith("sqlite"):
        engine = create_engine(url, connect_args={"check_same_thread": False})
        target = ":memory:" if not parsed.database else f"{parsed.database}.reporting.db"
        attach_reporting_schema(engine, target)
        return engine
    # Sin sentencias preparadas (pooler de Supabase en modo transacción), igual que la API.
    return create_engine(url, pool_pre_ping=True, connect_args=database._connect_args(url))


def reader_engine() -> Engine:
    return engine_for(resolve_url(READER_BLOCK, READER_ENV))


def writer_engine() -> Engine:
    return engine_for(resolve_url(WRITER_BLOCK, WRITER_ENV))


ENVIRONMENT_VARIABLE = "reporting-environment"  # Variable de Prefect
ENVIRONMENT_ENV = "REPORTING_ENVIRONMENT"


def default_environment() -> str:
    """`tags.environment` que lee el pipeline: `production` en producción, el de la API en local.

    Variable de entorno → Variable de Prefect `reporting-environment` → TELEMETRY_ENVIRONMENT de la
    API (el entorno que esta misma instalación escribe en los eventos).
    """
    value = os.getenv(ENVIRONMENT_ENV, "").strip()
    if not value:
        try:
            from prefect.variables import Variable

            value = (Variable.get(ENVIRONMENT_VARIABLE, default=None, _sync=True) or "").strip()
        except Exception:  # noqa: BLE001 - sin servidor de Prefect: se usa la configuración de la API
            value = ""
    if not value:
        from services.api import config

        value = config.TELEMETRY_ENVIRONMENT
    return value


def api_engine() -> Engine:
    from services import database

    return database.engine
