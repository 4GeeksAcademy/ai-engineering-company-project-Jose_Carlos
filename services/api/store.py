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

def _open_database(path: Path, **options) -> TinyDB:
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


# Abrimos o creamos la base de datos (persistente en disco)
db = _open_database(DB_PATH, ensure_ascii=False, indent=2)

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


# =========================================================
# INCIDENCIAS (gestor centralizado, CONTEXT-8)
# =========================================================

incidents_table = db.table("incidents")

# incident_id del CSV → id de la incidencia creada por el seed. Solo sirve para que el
# seed sea idempotente: el incident_id no forma parte del modelo Incident.
incident_seed_keys_table = db.table("incident_seed_keys")

# Los vectores de embeddings van en un archivo aparte y compacto: TinyDB relee db.json
# entero en cada operación y cientos de floats por incidencia lo harían lento e ilegible.
EMBEDDINGS_DB_PATH = DB_PATH.with_name(f"{DB_PATH.stem}.embeddings.json")
embeddings_db = _open_database(EMBEDDINGS_DB_PATH)
incident_embeddings_table = embeddings_db.table("incident_embeddings")

IncidentQuery = Query()


@_locked
def get_all_incidents() -> list[dict]:
    """Devuelve todas las incidencias."""
    return [_with_id(doc) for doc in incidents_table.all()]


@_locked
def get_incident_by_id(incident_id: int) -> dict | None:
    """Busca una incidencia por su ID."""
    return _with_id(incidents_table.get(doc_id=incident_id))


@_locked
def find_incident(title: str, created_at: str) -> dict | None:
    """Busca una incidencia por título y fecha de creación (control de duplicados del seed)."""
    return _with_id(
        incidents_table.get((IncidentQuery.title == title) & (IncidentQuery.created_at == created_at))
    )


@_locked
def create_incident(incident_data: dict) -> dict:
    """Guarda una nueva incidencia y la devuelve con su ID."""
    incident_id = incidents_table.insert(_to_storable(incident_data))
    return get_incident_by_id(incident_id)


@_locked
def update_incident(incident_id: int, data: dict) -> dict | None:
    """Actualiza los campos indicados. Devuelve la incidencia o None si no existe."""
    if not incidents_table.contains(doc_id=incident_id):
        return None
    incidents_table.update(_to_storable(data), doc_ids=[incident_id])
    return get_incident_by_id(incident_id)


@_locked
def clear_incidents() -> None:
    """Vacía las incidencias, las claves del seed y sus embeddings."""
    incidents_table.truncate()
    incident_seed_keys_table.truncate()
    incident_embeddings_table.truncate()


@_locked
def get_seed_key(csv_incident_id: str) -> dict | None:
    """Devuelve el registro del seed para un incident_id del CSV, si ya se cargó."""
    return incident_seed_keys_table.get(IncidentQuery.csv_incident_id == csv_incident_id)


@_locked
def add_seed_key(csv_incident_id: str, incident_id: int) -> None:
    """Anota que la fila del CSV con ese incident_id ya está cargada."""
    incident_seed_keys_table.insert({"csv_incident_id": csv_incident_id, "incident_id": incident_id})


@_locked
def get_incident_embeddings() -> list[dict]:
    """Devuelve todos los embeddings: {incident_id, model, text_hash, vector}."""
    return [dict(doc) for doc in incident_embeddings_table.all()]


@_locked
def save_incident_embeddings(records: list[dict]) -> None:
    """Guarda (o reemplaza) el embedding de cada incidencia indicada."""
    for record in records:
        incident_embeddings_table.upsert(record, IncidentQuery.incident_id == record["incident_id"])
