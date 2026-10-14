"""Siembra el inventario de Supabase con los datos mínimos de CONTEXT-9.

Uso (desde la raíz del repo, con DATABASE_URL en .env):
    uv run python -m services.seed_inventory [--user-email admin@trackflow.com]

- Crea las tablas que falten y los 6 SKUs (los que ya existan por código no se tocan).
- Registra las entradas y salidas solo si esos SKUs todavía no tienen movimientos, así que
  se puede ejecutar varias veces sin duplicar stock.
- Los movimientos pasan por las mismas reglas que la API (inventory_service): una salida que
  dejara el stock en negativo haría fallar el seed.
- El `user_uuid` de los movimientos es el de un usuario real de TinyDB: el indicado con
  --user-email o, si no se indica, el primer admin.
"""

import argparse
import sys

from sqlmodel import Session, select

from services import inventory_service
from services.api import user_service
from services.database import create_db_and_tables, engine
from services.models import SKU, StockEntry, StockExit
from services.schemas import SKUCreate, StockEntryCreate, StockExitCreate


SKUS = [
    ("Zapatilla blanca clásica - Talla 42", "CLT-SNK-W-42", "PureStep Footwear", "fashion", "LA"),
    ("Zapatilla blanca clásica - Talla 42", "CLT-SNK-W-42-Z", "PureStep Footwear", "fashion", "ZGZ"),
    ("Auriculares inalámbricos Pro", "TEC-EAR-001", "SoundWave Electronics", "electronics", "LA"),
    ("Sérum facial hidratante 30ml", "CSM-SRM-030", "GlowLab Cosmetics", "cosmetics", "ZGZ"),
    ("Chino slim fit - marino 32/32", "CLT-CHN-N-32", "UrbanThread", "fashion", "LA"),
    ("Cargador rápido USB-C 65W", "TEC-CHG-065", "SoundWave Electronics", "electronics", "ZGZ"),
]

# (código SKU, cantidad, referencia, almacén)
ENTRIES = [
    ("CLT-SNK-W-42", 120, "PO-2024-0098", "LA"),
    ("CLT-SNK-W-42", 80, "GR-LA-0234", "LA"),  # segunda recepción del mismo SKU
    ("CLT-SNK-W-42-Z", 60, "PO-2024-0101", "ZGZ"),
    ("TEC-EAR-001", 50, "PO-2024-0112", "LA"),
    ("TEC-EAR-001", 15, "GR-ZGZ-0064", "ZGZ"),  # mismo SKU en el otro almacén (regla 6)
    ("CSM-SRM-030", 200, "GR-ZGZ-0057", "ZGZ"),
    ("CLT-CHN-N-32", 40, "PO-2024-0120", "LA"),
    ("TEC-CHG-065", 75, "GR-ZGZ-0061", "ZGZ"),
]

# (código SKU, cantidad, tipo, número de seguimiento, almacén)
EXITS = [
    ("CLT-SNK-W-42", 30, "dispatch", "1Z999AA10123456784", "LA"),
    ("TEC-EAR-001", 2, "loss", None, "LA"),
    ("CSM-SRM-030", 45, "dispatch", "1Z999AA10123456791", "ZGZ"),
    ("CLT-SNK-W-42-Z", 1, "loss", None, "ZGZ"),
]

# Stock esperado tras el seed: {código: {almacén: unidades}} = entradas − salidas.
EXPECTED_STOCK = {
    "CLT-SNK-W-42": {"LA": 170, "ZGZ": 0},
    "CLT-SNK-W-42-Z": {"LA": 0, "ZGZ": 59},
    "TEC-EAR-001": {"LA": 48, "ZGZ": 15},
    "CSM-SRM-030": {"LA": 0, "ZGZ": 155},
    "CLT-CHN-N-32": {"LA": 40, "ZGZ": 0},
    "TEC-CHG-065": {"LA": 0, "ZGZ": 75},
}


def seed(db: Session, user_uuid: str) -> dict[str, int]:
    """Siembra SKUs y movimientos. Devuelve cuántos registros ha creado de cada tipo."""
    created = {"skus": 0, "entries": 0, "exits": 0}

    ids = {}
    for name, code, client_name, category, warehouse in SKUS:
        sku = db.exec(select(SKU).where(SKU.sku == code)).first()
        if sku is None:
            data = SKUCreate(name=name, sku=code, client_name=client_name, category=category, warehouse=warehouse)
            sku = inventory_service.create_sku(db, data)
            created["skus"] += 1
        ids[code] = sku.id

    seed_ids = list(ids.values())
    has_movements = (
        db.exec(select(StockEntry.id).where(StockEntry.sku_id.in_(seed_ids))).first() is not None
        or db.exec(select(StockExit.id).where(StockExit.sku_id.in_(seed_ids))).first() is not None
    )
    if has_movements:
        return created

    for code, quantity, reference, warehouse in ENTRIES:
        data = StockEntryCreate(sku_id=ids[code], quantity=quantity, reference=reference, warehouse=warehouse)
        inventory_service.register_entry(db, data, user_uuid)
        created["entries"] += 1

    for code, quantity, exit_type, tracking_number, warehouse in EXITS:
        data = StockExitCreate(
            sku_id=ids[code], quantity=quantity, exit_type=exit_type,
            tracking_number=tracking_number, warehouse=warehouse,
        )
        inventory_service.register_exit(db, data, user_uuid)
        created["exits"] += 1

    return created


def _seed_user(email: str | None) -> dict:
    if email:
        user = user_service.get_user_by_email(email)
        if user is None:
            sys.exit(f"No existe ningún usuario con el email {email} en TinyDB.")
        return user

    admins = [user for user in user_service.list_users() if user["role"] == "admin" and user["is_active"]]
    if not admins:
        sys.exit(
            "No hay ningún admin en TinyDB al que atribuir los movimientos. Crea uno con:\n"
            "  uv run python -m services.api.create_admin admin@trackflow.com 'una-contraseña-larga'"
        )
    return admins[0]


def main() -> None:
    parser = argparse.ArgumentParser(description="Siembra el inventario de Supabase (CONTEXT-9).")
    parser.add_argument("--user-email", help="Usuario de TinyDB al que se atribuyen los movimientos (por defecto, el primer admin).")
    args = parser.parse_args()

    user = _seed_user(args.user_email)
    create_db_and_tables()
    with Session(engine) as db:
        created = seed(db, user["id"])
        print(
            f"SKUs creados: {created['skus']}, entradas: {created['entries']}, salidas: {created['exits']} "
            f"(movimientos atribuidos a {user['email']})."
        )
        if not created["entries"]:
            print("Los SKUs del seed ya tenían movimientos: no se ha añadido ninguno.")

        print("\nStock por almacén:")
        for sku in inventory_service.list_skus(db):
            print(f"  {sku.sku:<16} {sku.warehouse:<4} current_stock={sku.current_stock:<5} {sku.stock_by_warehouse}")


if __name__ == "__main__":
    main()
