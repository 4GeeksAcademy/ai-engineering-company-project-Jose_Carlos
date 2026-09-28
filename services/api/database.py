from pathlib import Path

from tinydb import TinyDB, Query


# Ruta al archivo donde TinyDB guardará los datos
DB_PATH = Path(__file__).parent / "db.json"

# Abrimos o creamos la base de datos
db = TinyDB(DB_PATH)

# Tabla de proveedores
suppliers_table = db.table("suppliers")

# Objeto para construir consultas
SupplierQuery = Query()


def get_all_suppliers():
    """Devuelve todos los proveedores."""
    return suppliers_table.all()


def get_supplier_by_id(supplier_id: int):
    """Busca un proveedor por su ID."""
    return suppliers_table.get(doc_id=supplier_id)


def create_supplier(supplier_data: dict):
    """Guarda un nuevo proveedor y devuelve su ID."""
    return suppliers_table.insert(supplier_data)


def update_supplier(supplier_id: int, data: dict):
    """Actualiza los campos indicados de un proveedor."""
    suppliers_table.update(data, doc_ids=[supplier_id])


def delete_supplier(supplier_id: int):
    """Elimina un proveedor."""
    suppliers_table.remove(doc_ids=[supplier_id])