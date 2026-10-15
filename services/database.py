"""Las dos conexiones de base de datos de la API.

- TinyDB (archivo JSON local): usuarios, perfiles y autenticación, más proveedores e
  incidencias. Lo usan services/api/store.py y services/api/user_service.py.
- Supabase (PostgreSQL en la nube, vía SQLModel): inventario — SKUs, entradas y salidas de
  stock. Lo usa solo services/routers/inventory.py, con una sesión por petición (get_db).

Ninguna tabla de usuarios se replica en Supabase: los movimientos guardan el `user_uuid`
del usuario de TinyDB que los registró.
"""

import os
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, SQLModel, create_engine
from tinydb import TinyDB

from services.api import config


# =========================================================
# TinyDB: usuarios y autenticación
# =========================================================

# Se puede cambiar con la variable de entorno TINYDB_PATH (los tests la usan para no tocar
# nunca services/api/db.json).
TINYDB_PATH = Path(os.getenv("TINYDB_PATH", Path(__file__).parent / "api" / "db.json"))


def open_tinydb(path: Path, **options) -> TinyDB:
    """Abre (o crea) un archivo TinyDB y comprueba que se puede leer.

    Sin esto, un archivo corrupto o sin permisos no falla al arrancar sino en la primera
    petición, con un error que no dice qué archivo es.
    """
    try:
        database = TinyDB(path, **options)
        database.tables()  # fuerza la lectura del JSON
    except (OSError, ValueError) as error:
        raise RuntimeError(
            f"No se puede abrir la base de datos {path}: {error}. "
            "Comprueba que el archivo es un JSON válido y que hay permisos de lectura y escritura."
        ) from error
    return database


tinydb = open_tinydb(TINYDB_PATH, ensure_ascii=False, indent=2)


# =========================================================
# Supabase (PostgreSQL): inventario
# =========================================================


def _engine_url(url: str) -> str:
    """Usa el driver psycopg 3 para las cadenas `postgres://` / `postgresql://` que da Supabase."""
    if url.startswith(("http://", "https://")):
        # Es la URL del proyecto (la de la API REST), no la de PostgreSQL: SQLAlchemy fallaría
        # con un "Can't load plugin: sqlalchemy.dialects:https" que no dice qué hacer.
        raise RuntimeError(
            "DATABASE_URL contiene la URL del proyecto de Supabase (https://<ref>.supabase.co), que es "
            "para su API REST. SQLModel necesita la cadena de conexión PostgreSQL con la contraseña de "
            "la base de datos: Supabase > Connect > Connection String > Session pooler, con la forma "
            "postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres"
        )
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def _connect_args(url: str) -> dict:
    if url.startswith("postgresql+psycopg://"):
        # El pooler de Supabase en modo transacción (puerto 6543) no admite sentencias
        # preparadas; desactivarlas funciona igual con el modo sesión (5432) y la conexión directa.
        return {"prepare_threshold": None}
    return {}


DATABASE_URL = _engine_url(config.DATABASE_URL)

# create_engine no conecta todavía: la primera conexión se abre al arrancar (create_db_and_tables)
# o en la primera petición. pool_pre_ping descarta las conexiones que Supabase haya cerrado.
engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args=_connect_args(DATABASE_URL))


def safe_database_url() -> str:
    """La URL del inventario sin la contraseña, para mensajes de error y logs."""
    return make_url(DATABASE_URL).render_as_string(hide_password=True)


INVENTORY_TABLES = ("sku", "stock_entry", "stock_exit")


def row_level_security_statements(dialect_name: str) -> list[str]:
    """Activa RLS en las tablas de inventario de Supabase.

    Supabase publica las tablas del esquema `public` en su API REST, a la que se llega con la
    clave publishable (pública). Con RLS activado y sin políticas, esa vía queda cerrada: solo
    la API de FastAPI (que conecta como propietaria de las tablas) puede leer y escribir, con
    su autenticación y sus reglas de stock.
    """
    if dialect_name != "postgresql":
        return []
    return [f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY" for table in INVENTORY_TABLES]


def create_db_and_tables() -> None:
    """Crea en Supabase las tablas de inventario que falten (no modifica las existentes)."""
    import services.models  # noqa: F401 — registra SKU, StockEntry y StockExit en SQLModel.metadata

    try:
        SQLModel.metadata.create_all(engine)
        statements = row_level_security_statements(engine.dialect.name)
        if statements:
            with engine.begin() as connection:
                for statement in statements:
                    connection.execute(text(statement))
    except SQLAlchemyError as error:
        raise RuntimeError(
            f"No se pudo inicializar la base de datos de inventario ({safe_database_url()}): "
            f"{type(error).__name__}. Revisa DATABASE_URL en .env y que el proyecto de Supabase esté activo."
        ) from error


def get_db():
    """Dependencia de FastAPI: una sesión de inventario por petición, cerrada al terminar."""
    with Session(engine) as session:
        yield session
