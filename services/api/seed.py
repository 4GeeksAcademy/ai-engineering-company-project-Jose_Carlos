import sys
from datetime import datetime, timezone

from pydantic import ValidationError

from services.api import store
from services.api.models import SupplierCreate


# Proveedores iniciales, copiados tal cual de audit/CONTEXTS/CONTEXT-7-trackflow.es.md.
SUPPLIERS_SEED = [
    {
        "name": "UPS Ground",
        "country": "USA",
        "categories": ["carrier_last_mile"],
        "rate_per_shipment": 7.45,
        "currency": "USD",
        "status": "active",
        "service_zone": "West Coast",
        "contact_email": "business@ups.com",
        "notes": "Carrier principal para entregas locales en Los Ángeles y alrededores."
    },
    {
        "name": "FedEx Ground",
        "country": "USA",
        "categories": ["carrier_last_mile"],
        "rate_per_shipment": 7.90,
        "currency": "USD",
        "status": "active",
        "service_zone": "Continental USA",
        "contact_email": "business.solutions@fedex.com"
    },
    {
        "name": "DHL Express USA",
        "country": "USA",
        "categories": ["carrier_last_mile", "carrier_international"],
        "rate_per_shipment": 14.20,
        "currency": "USD",
        "status": "active",
        "service_zone": "Continental USA + International",
        "contact_email": "business.us@dhl.com",
        "notes": "Usado para envíos urgentes y exportaciones a Europa."
    },
    {
        "name": "OnTrac",
        "country": "USA",
        "categories": ["carrier_last_mile"],
        "rate_per_shipment": 6.10,
        "currency": "USD",
        "status": "active",
        "service_zone": "West Coast",
        "contact_email": "solutions@ontrac.com",
        "notes": "Carrier regional. Mejor tarifa en la zona de Los Ángeles."
    },
    {
        "name": "Laser Ship",
        "country": "USA",
        "categories": ["carrier_last_mile"],
        "rate_per_shipment": 5.80,
        "currency": "USD",
        "status": "suspended",
        "service_zone": "East Coast",
        "contact_email": "business@lasership.com",
        "notes": "Suspendido. Tasa de incidencias superior al 8% en Q3."
    },
    {
        "name": "PackSource LA",
        "country": "USA",
        "categories": ["packaging_materials"],
        "rate_per_shipment": 0.42,
        "currency": "USD",
        "status": "active",
        "contact_email": "orders@packsource.com",
        "notes": "Cajas, relleno y precinto para el almacén de Los Ángeles."
    },
    {
        "name": "CleanTeam West",
        "country": "USA",
        "categories": ["cleaning_and_facilities"],
        "rate_per_shipment": 1800.0,
        "currency": "USD",
        "status": "active",
        "contact_email": "accounts@cleanteamwest.com",
        "notes": "Tarifa mensual por servicio de limpieza del almacén de LA."
    },
    {
        "name": "MRW España",
        "country": "Spain",
        "categories": ["carrier_last_mile"],
        "rate_per_shipment": 4.90,
        "currency": "EUR",
        "status": "active",
        "service_zone": "Península Ibérica",
        "contact_email": "clientes.empresa@mrw.es",
        "notes": "Carrier principal para entregas en España. Contrato negociado por volumen."
    },
    {
        "name": "SEUR",
        "country": "Spain",
        "categories": ["carrier_last_mile"],
        "rate_per_shipment": 5.20,
        "currency": "EUR",
        "status": "active",
        "service_zone": "Península Ibérica + Baleares",
        "contact_email": "grandes.cuentas@seur.com"
    },
    {
        "name": "DHL Express España",
        "country": "Spain",
        "categories": ["carrier_last_mile", "carrier_international"],
        "rate_per_shipment": 12.80,
        "currency": "EUR",
        "status": "active",
        "service_zone": "España + Internacional",
        "contact_email": "business.es@dhl.com",
        "notes": "Envíos urgentes y exportaciones desde Zaragoza."
    },
    {
        "name": "Nacex",
        "country": "Spain",
        "categories": ["carrier_last_mile"],
        "rate_per_shipment": 4.60,
        "currency": "EUR",
        "status": "active",
        "service_zone": "Aragón y zona norte",
        "contact_email": "empresas@nacex.es",
        "notes": "Carrier regional con buena cobertura en Aragón."
    },
    {
        "name": "Logística Inversa Iberia",
        "country": "Spain",
        "categories": ["reverse_logistics"],
        "rate_per_shipment": 6.30,
        "currency": "EUR",
        "status": "active",
        "contact_email": "operaciones@liiberia.es",
        "notes": "Gestión de devoluciones para el almacén de Zaragoza."
    },
    {
        "name": "Embalajes Zaragoza S.L.",
        "country": "Spain",
        "categories": ["packaging_materials"],
        "rate_per_shipment": 0.28,
        "currency": "EUR",
        "status": "active",
        "contact_email": "pedidos@embalajeszgz.es"
    },
    {
        "name": "SAP WM Cloud",
        "country": "USA",
        "categories": ["it_and_wms_software"],
        "rate_per_shipment": 2200.0,
        "currency": "USD",
        "status": "suspended",
        "contact_email": "enterprise@sap.com",
        "notes": "Suspendido. Andrés está evaluando alternativas más ligeras para el almacén de LA."
    },
    {
        "name": "ReturnBear",
        "country": "USA",
        "categories": ["reverse_logistics"],
        "rate_per_shipment": 4.15,
        "currency": "USD",
        "status": "active",
        "service_zone": "West Coast",
        "contact_email": "partnerships@returnbear.com",
        "notes": "Gestión de devoluciones para clientes de Los Ángeles."
    }
]


def seed_suppliers(force: bool = False) -> dict:
    """Carga SUPPLIERS_SEED en TinyDB.

    - force=False: idempotente. Un proveedor se considera ya existente si hay
      otro con el mismo `name` (los nombres del seed son únicos); solo se
      insertan los que faltan.
    - force=True: vacía la tabla y vuelve a insertar todo el seed.
    """
    # Validamos TODO el seed con el mismo modelo que usa la API antes de tocar la base de
    # datos: con force, una entrada inválida a mitad dejaría la tabla vacía o incompleta.
    suppliers = [SupplierCreate(**entry) for entry in SUPPLIERS_SEED]

    if force:
        store.clear_suppliers()

    inserted = 0
    skipped = 0
    for supplier in suppliers:
        if not force and store.get_supplier_by_name(supplier.name) is not None:
            skipped += 1
            continue

        data = supplier.model_dump(mode="json")
        data["updated_at"] = datetime.now(tz=timezone.utc).isoformat()
        store.create_supplier(data)
        inserted += 1

    print(f"Seed complete: inserted={inserted}, skipped={skipped}")
    return {"inserted": inserted, "skipped": skipped}


def main() -> None:
    try:
        seed_suppliers(force="--force" in sys.argv[1:])
    except ValidationError as error:
        print("El seed de proveedores contiene datos no válidos; no se ha modificado nada:", file=sys.stderr)
        for issue in error.errors():
            field = ".".join(str(part) for part in issue["loc"]) or "datos"
            print(f"  - {field}: {issue['msg']}", file=sys.stderr)
        sys.exit(1)
    except (OSError, ValueError) as error:
        # Fallo al leer o escribir TinyDB (archivo bloqueado, sin permisos o JSON corrupto).
        print(f"No se pudo escribir en la base de datos: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
