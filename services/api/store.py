import os
import threading
from datetime import datetime
from functools import wraps
from pathlib import Path

from tinydb import Query, TinyDB


# Ruta al archivo donde TinyDB guarda los datos.
# Se puede cambiar con la variable de entorno TINYDB_PATH (los tests la usan
# para no tocar nunca services/api/db.json).
DB_PATH = Path(os.getenv("TINYDB_PATH", Path(__file__).parent / "db.json"))

# Abrimos o creamos la base de datos (persistente en disco)
db = TinyDB(DB_PATH, ensure_ascii=False, indent=2)

# Tabla de proveedores
suppliers_table = db.table("suppliers")

# Objeto para construir consultas
SupplierQuery = Query()

# TinyDB no es thread-safe y FastAPI ejecuta los endpoints sync en un pool de hilos:
# sin este lock, dos peticiones simultáneas pueden leer el JSON a medio escribir.
_lock = threading.RLock()


def _locked(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        with _lock:
            return func(*args, **kwargs)

    return wrapper


def _with_id(doc):
    """Devuelve el documento como dict con su doc_id en el campo `id`."""
    if doc is None:
        return None
    return {**doc, "id": doc.doc_id}


def _to_storable(data: dict) -> dict:
    """Convierte updated_at a texto ISO 8601 y descarta `id` (lo gestiona TinyDB)."""
    data = {key: value for key, value in data.items() if key != "id"}
    if isinstance(data.get("updated_at"), datetime):
        data["updated_at"] = data["updated_at"].isoformat()
    return data


@_locked
def get_all_suppliers() -> list[dict]:
    """Devuelve todos los proveedores."""
    return [_with_id(doc) for doc in suppliers_table.all()]


@_locked
def get_supplier_by_id(supplier_id: int) -> dict | None:
    """Busca un proveedor por su ID."""
    return _with_id(suppliers_table.get(doc_id=supplier_id))


@_locked
def get_supplier_by_name(name: str) -> dict | None:
    """Busca un proveedor por su nombre exacto."""
    return _with_id(suppliers_table.get(SupplierQuery.name == name))


@_locked
def create_supplier(supplier_data: dict) -> dict:
    """Guarda un nuevo proveedor y lo devuelve con su ID."""
    supplier_id = suppliers_table.insert(_to_storable(supplier_data))
    return get_supplier_by_id(supplier_id)


@_locked
def update_supplier(supplier_id: int, data: dict) -> dict | None:
    """Actualiza los campos indicados. Devuelve el proveedor o None si no existe."""
    if not suppliers_table.contains(doc_id=supplier_id):
        return None
    suppliers_table.update(_to_storable(data), doc_ids=[supplier_id])
    return get_supplier_by_id(supplier_id)


@_locked
def delete_supplier(supplier_id: int) -> dict | None:
    """Elimina un proveedor. Devuelve cómo era antes de borrarlo, o None si no existe."""
    supplier = get_supplier_by_id(supplier_id)
    if supplier is not None:
        suppliers_table.remove(doc_ids=[supplier_id])
    return supplier


@_locked
def clear_suppliers() -> None:
    """Vacía la tabla de proveedores."""
    suppliers_table.truncate()
