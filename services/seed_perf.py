"""Seed de volumen para medir rendimiento (hito 13: caching).

Uso (desde la raíz del repo, con DATABASE_URL en .env y la API parada o no):
    uv run python -m services.seed_perf                 # siembra con los valores por defecto
    uv run python -m services.seed_perf --skus 300      # menos volumen
    uv run python -m services.seed_perf --no-embeddings # no calcula ahora los embeddings
    uv run python -m services.seed_perf --dry-run       # genera y resume, sin escribir nada
    uv run python -m services.seed_perf --counts        # solo cuenta filas
    uv run python -m services.seed_perf --purge         # borra todo lo que creó este seed

Qué siembra y por qué:
- Inventario (Supabase): SKUs de ~40 marcas cliente ficticias, con un año de recepciones,
  despachos y pérdidas. Alimenta GET /inventory/products (dos agregaciones SUM ... GROUP BY
  sobre todos los movimientos) y GET /inventory/orders (todos los movimientos con su SKU),
  las lecturas más caras de la API.
- Incidencias (TinyDB): incidencias de las sedes de Los Ángeles y Zaragoza que citan esas
  marcas, SKUs, transportistas y números de seguimiento. Alimentan el listado, el resumen y
  los duplicados (similitud de todas contra todas).

Cómo se mantiene coherente:
- El stock se SIMULA día a día por SKU: un despacho solo ocurre si hay unidades, y una
  recepción llega cuando el stock baja del punto de pedido. Así nunca queda negativo y hay
  de todo: SKUs con mucho stock, con stock bajo (1–49), agotados y descatalogados.
- Antes del commit se recalcula el stock con inventory_service.stock_levels y, si algún
  SKU quedara en negativo, se deshace todo (una sola transacción).
- Cada fila pasa por los schemas de la API (SKUCreate, StockEntryCreate, StockExitCreate).
- Generador con semilla fija: dos ejecuciones producen exactamente los mismos datos.

Cómo se deshace:
- Las marcas de este seed son ficticias y solo existen aquí: `--purge` borra sus SKUs y
  sus movimientos (por client_name) sin tocar los 6 SKUs de services/seed_inventory.py ni
  los que se hayan dado de alta a mano.
- Las incidencias creadas se anotan en la tabla TinyDB `perf_seed_incidents` (mismo patrón
  que `incident_seed_keys`); `--purge` borra esas incidencias y sus embeddings.
"""

import argparse
import math
import random
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import delete, func, insert
from sqlmodel import Session, select

from packages.shared.incident_model import validate_incident_fields
from services import inventory_service
from services.api import store, user_service
from services.database import create_db_and_tables, engine, tinydb
from services.models import SKU, StockEntry, StockExit
from services.schemas import SKUCreate, StockEntryCreate, StockExitCreate


RANDOM_SEED = 13
DAYS = 365
TODAY = date(2026, 10, 20)
START = TODAY - timedelta(days=DAYS)

# Tabla TinyDB con los ids de las incidencias que ha creado este seed (para --purge).
perf_seed_incidents_table = tinydb.table("perf_seed_incidents")


# =========================================================
# CATÁLOGO: marcas cliente y productos
# =========================================================


@dataclass(frozen=True)
class Brand:
    name: str
    code: str
    category: str
    warehouses: tuple[str, ...]  # almacenes donde TrackFlow le guarda stock
    lines: tuple[str, ...]       # claves de PRODUCTS que vende


# Marcas de e-commerce ficticias. Las de EE. UU. trabajan con Los Ángeles, las europeas con
# Zaragoza y unas pocas con los dos almacenes (mismo producto, un SKU por almacén).
BRANDS = [
    # Moda
    Brand("Northbound Apparel", "NBA", "fashion", ("LA",), ("tee", "hoodie", "jacket", "cap")),
    Brand("Calle Verde", "CVR", "fashion", ("ZGZ",), ("tee", "dress", "jeans", "socks")),
    Brand("Stride Lab", "STL", "fashion", ("LA", "ZGZ"), ("runner", "socks", "cap")),
    Brand("Moana Swim", "MSW", "fashion", ("LA",), ("swim", "tee", "tote")),
    Brand("Ébano Leather Co.", "EBL", "fashion", ("ZGZ",), ("tote", "belt", "wallet")),
    Brand("Pacific Denim Works", "PDW", "fashion", ("LA",), ("jeans", "jacket", "tee")),
    Brand("Lino & Co", "LNC", "fashion", ("ZGZ",), ("shirt", "dress", "trousers")),
    Brand("Alpina Trail", "ALT", "fashion", ("ZGZ", "LA"), ("jacket", "hoodie", "socks", "runner")),
    Brand("Sunday Basics", "SDB", "fashion", ("LA",), ("tee", "socks", "hoodie", "trousers")),
    Brand("Mar de Fondo", "MDF", "fashion", ("ZGZ",), ("swim", "shirt", "tote")),
    Brand("Kinetic Kids", "KNK", "fashion", ("LA",), ("tee", "runner", "cap")),
    Brand("Atelier Nómada", "ATN", "fashion", ("ZGZ",), ("dress", "belt", "wallet", "shirt")),
    Brand("Westline Workwear", "WLW", "fashion", ("LA",), ("trousers", "jacket", "boots")),
    Brand("Pirineo Outdoor", "PRO", "fashion", ("ZGZ",), ("boots", "jacket", "socks")),
    # Electrónica
    Brand("Voltix", "VTX", "electronics", ("LA", "ZGZ"), ("charger", "cable", "powerbank", "hub")),
    Brand("Echo Peak Audio", "EPA", "electronics", ("LA",), ("earbuds", "headphones", "speaker")),
    Brand("Nimbus Home", "NBH", "electronics", ("ZGZ",), ("smartplug", "bulb", "camera")),
    Brand("CaseCraft", "CCR", "electronics", ("LA",), ("case", "screen", "cable")),
    Brand("Bitwise Peripherals", "BWP", "electronics", ("ZGZ",), ("keyboard", "mouse", "hub")),
    Brand("Pulse Wearables", "PWR", "electronics", ("LA",), ("watch", "band", "charger")),
    Brand("Ondas Audio", "OND", "electronics", ("ZGZ",), ("speaker", "earbuds", "cable")),
    Brand("Lumen Gear", "LMG", "electronics", ("LA",), ("ringlight", "tripod", "powerbank")),
    Brand("Tierra Tech", "TRT", "electronics", ("ZGZ",), ("case", "screen", "charger")),
    Brand("Arcade Nest", "ARN", "electronics", ("LA",), ("controller", "headphones", "cable")),
    # Cosmética
    Brand("Aurora Skin", "ARS", "cosmetics", ("LA",), ("serum", "moisturizer", "cleanser", "eye")),
    Brand("Botánica Mediterránea", "BTM", "cosmetics", ("ZGZ",), ("bodyoil", "soap", "shampoo")),
    Brand("Solace SPF", "SSP", "cosmetics", ("LA", "ZGZ"), ("sunscreen", "lipbalm", "moisturizer")),
    Brand("Raíz Capilar", "RZC", "cosmetics", ("ZGZ",), ("shampoo", "mask", "hairoil")),
    Brand("Velvet Hue", "VLH", "cosmetics", ("LA",), ("foundation", "lipstick", "mascara")),
    Brand("Pure Ritual", "PRT", "cosmetics", ("LA",), ("cleanser", "toner", "serum")),
    Brand("Esencia Ibérica", "ESI", "cosmetics", ("ZGZ",), ("perfume", "bodyoil", "soap")),
    Brand("Gentle Bear", "GTB", "cosmetics", ("LA",), ("babylotion", "shampoo", "lipbalm")),
    Brand("Nórdica Derm", "NDD", "cosmetics", ("ZGZ",), ("moisturizer", "eye", "toner")),
    Brand("Coral Bay Beauty", "CBB", "cosmetics", ("LA",), ("lipstick", "foundation", "perfume")),
    Brand("Huerta Natural", "HTN", "cosmetics", ("ZGZ",), ("soap", "mask", "lipbalm")),
    Brand("Midnight Apothecary", "MDA", "cosmetics", ("LA",), ("serum", "perfume", "bodyoil")),
]
BRAND_NAMES = tuple(brand.name for brand in BRANDS)

SIZES_TOP = ("XS", "S", "M", "L", "XL")
SIZES_SHOE = ("38", "39", "40", "41", "42", "43", "44", "45")
SIZES_JEANS = ("28/32", "30/32", "32/32", "34/32", "36/34")
COLORS = {
    "BLK": "negro", "WHT": "blanco", "NAV": "marino", "OLV": "oliva", "SND": "arena",
    "RED": "rojo", "GRY": "gris", "BLU": "azul", "TRC": "teja", "PNK": "rosa",
}

# clave: (código, nombre, variantes de color, variantes de talla/capacidad, precio unitario
# aproximado en USD, unidades por caja de proveedor)
PRODUCTS = {
    # moda
    "tee": ("TEE", "Camiseta algodón orgánico", ("BLK", "WHT", "NAV", "OLV", "SND"), SIZES_TOP, 24, 24),
    "hoodie": ("HOD", "Sudadera con capucha", ("BLK", "GRY", "NAV", "OLV"), SIZES_TOP, 58, 12),
    "jacket": ("JKT", "Chaqueta cortavientos", ("BLK", "NAV", "RED", "OLV"), SIZES_TOP, 120, 8),
    "cap": ("CAP", "Gorra béisbol ajustable", ("BLK", "NAV", "SND", "RED"), ("U",), 22, 24),
    "dress": ("DRS", "Vestido midi de lino", ("SND", "TRC", "BLU", "BLK"), SIZES_TOP, 79, 10),
    "jeans": ("JNS", "Vaquero slim", ("BLU", "BLK", "GRY"), SIZES_JEANS, 69, 12),
    "socks": ("SCK", "Calcetines técnicos pack 3", ("BLK", "WHT", "GRY"), ("S", "M", "L"), 15, 48),
    "runner": ("RUN", "Zapatilla running", ("BLK", "WHT", "BLU", "RED"), SIZES_SHOE, 110, 6),
    "swim": ("SWM", "Bañador de secado rápido", ("NAV", "RED", "BLU", "PNK"), SIZES_TOP, 45, 20),
    "tote": ("TOT", "Bolso tote", ("BLK", "SND", "TRC"), ("U",), 89, 10),
    "belt": ("BLT", "Cinturón de piel", ("BLK", "TRC"), ("85", "95", "105"), 49, 20),
    "wallet": ("WAL", "Cartera de piel", ("BLK", "TRC", "NAV"), ("U",), 55, 20),
    "shirt": ("SHT", "Camisa de lino", ("WHT", "SND", "BLU"), SIZES_TOP, 65, 12),
    "trousers": ("TRS", "Pantalón chino", ("SND", "NAV", "OLV", "BLK"), SIZES_JEANS, 59, 12),
    "boots": ("BOT", "Bota de montaña impermeable", ("BLK", "TRC", "GRY"), SIZES_SHOE, 149, 6),
    # electrónica
    "charger": ("CHG", "Cargador rápido USB-C", ("BLK", "WHT"), ("30W", "65W", "100W"), 39, 30),
    "cable": ("CBL", "Cable USB-C trenzado", ("BLK", "WHT", "GRY"), ("1M", "2M"), 14, 50),
    "powerbank": ("PWB", "Batería externa", ("BLK", "WHT"), ("10K", "20K"), 49, 20),
    "hub": ("HUB", "Hub USB-C 7 en 1", ("GRY",), ("U",), 59, 20),
    "earbuds": ("EAR", "Auriculares inalámbricos", ("BLK", "WHT"), ("U",), 129, 16),
    "headphones": ("HPH", "Auriculares diadema ANC", ("BLK", "SND", "NAV"), ("U",), 249, 8),
    "speaker": ("SPK", "Altavoz Bluetooth resistente al agua", ("BLK", "BLU", "RED"), ("U",), 89, 12),
    "smartplug": ("PLG", "Enchufe inteligente Wi-Fi", ("WHT",), ("EU", "US"), 19, 40),
    "bulb": ("BLB", "Bombilla LED inteligente", ("WHT",), ("E27", "E14"), 15, 40),
    "camera": ("CAM", "Cámara de seguridad interior", ("WHT", "BLK"), ("2K",), 69, 12),
    "case": ("CSE", "Funda móvil antigolpes", ("BLK", "BLU", "PNK", "OLV"), ("IP15", "IP16", "S24", "PX9"), 29, 50),
    "screen": ("SCR", "Protector de pantalla cristal", ("U",), ("IP15", "IP16", "S24", "PX9"), 12, 100),
    "keyboard": ("KBD", "Teclado mecánico compacto", ("BLK", "WHT"), ("ES", "US"), 99, 10),
    "mouse": ("MSE", "Ratón inalámbrico ergonómico", ("BLK", "GRY"), ("U",), 45, 20),
    "watch": ("WCH", "Reloj deportivo GPS", ("BLK", "NAV", "PNK"), ("41", "45"), 199, 10),
    "band": ("BND", "Correa de silicona", ("BLK", "NAV", "PNK", "OLV", "RED"), ("41", "45"), 19, 50),
    "ringlight": ("RGL", "Aro de luz LED 10 pulgadas", ("BLK",), ("U",), 35, 12),
    "tripod": ("TRP", "Trípode extensible para móvil", ("BLK",), ("U",), 29, 20),
    "controller": ("CTL", "Mando inalámbrico", ("BLK", "WHT", "RED"), ("U",), 59, 12),
    # cosmética
    "serum": ("SRM", "Sérum facial", ("U",), ("VITC30", "HYA30", "RET30"), 34, 48),
    "moisturizer": ("MST", "Crema hidratante", ("U",), ("50ML", "100ML"), 29, 48),
    "cleanser": ("CLN", "Gel limpiador facial", ("U",), ("150ML", "300ML"), 18, 48),
    "eye": ("EYE", "Contorno de ojos", ("U",), ("15ML",), 27, 48),
    "bodyoil": ("BOL", "Aceite corporal", ("U",), ("100ML", "200ML"), 24, 36),
    "soap": ("SOP", "Jabón artesanal", ("U",), ("OLIVA", "LAVANDA", "ROMERO"), 7, 96),
    "shampoo": ("SHP", "Champú", ("U",), ("SOLIDO75G", "250ML", "500ML"), 14, 48),
    "sunscreen": ("SPF", "Protector solar SPF50", ("U",), ("50ML", "200ML"), 22, 48),
    "lipbalm": ("LPB", "Bálsamo labial", ("U",), ("NAT", "FRESA", "MENTA"), 6, 120),
    "mask": ("MSK", "Mascarilla capilar", ("U",), ("200ML",), 21, 36),
    "hairoil": ("HOL", "Aceite capilar de argán", ("U",), ("50ML", "100ML"), 26, 36),
    "foundation": ("FND", "Base de maquillaje fluida", ("U",), ("110", "120", "210", "230", "320", "340"), 32, 36),
    "lipstick": ("LPS", "Barra de labios mate", ("RED", "PNK", "TRC"), ("U",), 19, 60),
    "mascara": ("MSC", "Máscara de pestañas", ("BLK",), ("U",), 17, 60),
    "toner": ("TNR", "Tónico facial", ("U",), ("200ML",), 19, 48),
    "perfume": ("PRF", "Eau de parfum", ("U",), ("50ML", "100ML"), 75, 24),
    "babylotion": ("BBL", "Loción corporal bebé", ("U",), ("250ML",), 12, 48),
}

# Reparto de SKUs del catálogo de TrackFlow por categoría.
CATEGORY_SHARE = {"fashion": 0.5, "electronics": 0.27, "cosmetics": 0.23}

# Transportistas por almacén: (nombre, generador de número de seguimiento)
DIGITS = "0123456789"
ALNUM = "0123456789ABCDEFGHJKLMNPRSTUVWXYZ"


def _rand(rng: random.Random, alphabet: str, length: int) -> str:
    return "".join(rng.choice(alphabet) for _ in range(length))


CARRIERS = {
    "LA": [
        ("UPS", 0.38, lambda rng: "1Z" + _rand(rng, ALNUM, 6) + "03" + _rand(rng, DIGITS, 8)),
        ("FedEx", 0.27, lambda rng: _rand(rng, DIGITS, 12)),
        ("USPS", 0.20, lambda rng: "9400" + _rand(rng, DIGITS, 18)),
        ("OnTrac", 0.15, lambda rng: "D" + _rand(rng, DIGITS, 14)),
    ],
    "ZGZ": [
        ("SEUR", 0.35, lambda rng: _rand(rng, DIGITS, 14)),
        ("Correos Express", 0.30, lambda rng: "3230" + _rand(rng, DIGITS, 12)),
        ("GLS", 0.20, lambda rng: _rand(rng, DIGITS, 11)),
        ("DHL Parcel", 0.15, lambda rng: "JJD" + _rand(rng, DIGITS, 18)),
    ],
}

# Hora local de apertura del muelle y desfase con UTC (sin horario de verano: basta para el seed).
WAREHOUSE_HOURS = {"LA": (7, 19, -8), "ZGZ": (8, 20, 1)}


# =========================================================
# GENERACIÓN DE SKUs
# =========================================================


def build_skus(rng: random.Random, target: int) -> list[dict]:
    """Variantes de todas las marcas hasta llegar a ~target SKUs (cada uno con su perfil de demanda)."""
    candidates = []
    for brand in BRANDS:
        for line in brand.lines:
            code, name, colors, sizes, price, case_pack = PRODUCTS[line]
            for color in colors:
                for size in sizes:
                    candidates.append((brand, line, code, name, color, size, price, case_pack))
    rng.shuffle(candidates)
    # Cuotas por categoría: sin ellas la moda (talla × color) se llevaría casi todos los SKUs.
    quota = {category: math.ceil(target * share) for category, share in CATEGORY_SHARE.items()}
    taken = dict.fromkeys(quota, 0)
    picked = []
    for candidate in candidates:
        category = candidate[0].category
        if taken[category] < quota[category]:
            picked.append(candidate)
            taken[category] += len(candidate[0].warehouses)

    skus = []
    seen = set()
    for brand, line, code, name, color, size, price, case_pack in picked:
        for position, warehouse in enumerate(brand.warehouses):
            # Mismo producto en el segundo almacén: un SKU propio con sufijo -Z / -L.
            suffix = "" if position == 0 else ("-Z" if warehouse == "ZGZ" else "-L")
            parts = [brand.code, code] + [p for p in (color, size) if p != "U"]
            sku_code = "-".join(parts) + suffix
            if sku_code in seen:
                continue
            seen.add(sku_code)
            label = name
            if color != "U":
                label += f" {COLORS[color]}"
            if size != "U":
                label += f" - {size}"
            skus.append(
                {
                    "create": SKUCreate(
                        name=f"{label} | {brand.name}"[:200],
                        sku=sku_code,
                        client_name=brand.name,
                        category=brand.category,
                        warehouse=warehouse,
                    ),
                    "brand": brand,
                    "price": price,
                    "case_pack": case_pack,
                    # Demanda media en unidades/día: pocos SKUs venden mucho (larga cola).
                    "daily_demand": round(rng.lognormvariate(-2.6, 1.0), 3),
                    # 10 % se dejan de reponer a mitad de año (descatalogados) y 7 % se lanzan tarde.
                    "lifecycle": rng.choices(("normal", "discontinued", "late_launch"), (0.83, 0.10, 0.07))[0],
                }
            )
        if len(skus) >= target:
            break
    return skus[:target]


# =========================================================
# SIMULACIÓN DE MOVIMIENTOS
# =========================================================


def _season(day: date, category: str) -> float:
    """Multiplicador de demanda: fin de semana, Black Friday / Navidad, rebajas y verano."""
    factor = (1.15, 1.1, 1.1, 1.1, 1.2, 0.6, 0.35)[day.weekday()]
    if (day.month == 11 and day.day >= 20) or (day.month == 12 and day.day <= 22):
        factor *= 2.3
    elif day.month == 1 and day.day <= 15:
        factor *= 1.4
    if category == "cosmetics" and day.month in (6, 7, 8):
        factor *= 1.3  # protector solar y aceites corporales
    return factor


def _timestamp(rng: random.Random, day: date, warehouse: str) -> datetime:
    opens, closes, utc_offset = WAREHOUSE_HOURS[warehouse]
    local = datetime(day.year, day.month, day.day, tzinfo=timezone.utc) + timedelta(
        hours=rng.uniform(opens, closes)
    )
    return (local - timedelta(hours=utc_offset)).replace(microsecond=0)


def _poisson(rng: random.Random, mean: float) -> int:
    # Knuth: suficiente para medias pequeñas (pedidos por día de un SKU).
    limit, k, p = math.exp(-mean), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def simulate(rng: random.Random, skus: list[dict], users: list[str]) -> tuple[list[dict], list[dict]]:
    """Un año de operación por SKU. Devuelve (entradas, salidas) como dicts sin sku_id todavía."""
    entries, exits = [], []
    trackings = set()
    po_counter = {"PO": 4100, "ASN": 1200, "GR-LA": 300, "GR-ZGZ": 150}
    # Quién registra: el primer usuario es el jefe de turno y registra más movimientos.
    user_weights = [3] + [1] * (len(users) - 1)

    for index, sku in enumerate(skus):
        create: SKUCreate = sku["create"]
        home = create.warehouse
        case = sku["case_pack"]
        demand = sku["daily_demand"]
        # Cobertura objetivo de 60-90 días de venta, en cajas completas (mínimo unas pocas cajas).
        order_up_to = max(case * rng.randint(3, 6), math.ceil(demand * rng.randint(60, 90) / case) * case)
        reorder_point = max(case, int(order_up_to * 0.3))

        start = START + timedelta(days=rng.randint(0, 60))
        if sku["lifecycle"] == "late_launch":
            start = TODAY - timedelta(days=rng.randint(10, 45))
        stop_restock = TODAY + timedelta(days=1)
        if sku["lifecycle"] == "discontinued":
            stop_restock = START + timedelta(days=rng.randint(120, 300))

        stock = {home: 0}
        pending_arrival: date | None = start
        pending_qty = order_up_to

        # 8 % de los SKUs reciben además un lote en el otro almacén (regla 6: stock por almacén).
        other = "ZGZ" if home == "LA" else "LA"
        if rng.random() < 0.08:
            day = start + timedelta(days=rng.randint(20, 200))
            if day <= TODAY:
                qty = case * rng.randint(1, 3)
                entries.append(_entry(rng, index, qty, other, day, po_counter, users, user_weights))
                stock[other] = qty
                # Ese lote se despacha poco a poco desde el otro almacén.
                for _ in range(rng.randint(0, 3)):
                    out_day = day + timedelta(days=rng.randint(3, 90))
                    out_qty = min(stock[other], rng.randint(1, 4))
                    if out_day <= TODAY and out_qty > 0:
                        exits.append(_exit(rng, index, out_qty, other, out_day, "dispatch", trackings, users, user_weights))
                        stock[other] -= out_qty

        day = start
        while day <= TODAY:
            if pending_arrival is not None and day >= pending_arrival:
                # Las recepciones llegan alguna vez con unidades de menos o de más respecto al pedido.
                qty = max(case, pending_qty + rng.choice((0, 0, 0, 0, -case, case)))
                entries.append(_entry(rng, index, qty, home, day, po_counter, users, user_weights))
                stock[home] += qty
                pending_arrival = None

            orders = _poisson(rng, demand * _season(day, create.category) / 1.6)
            for _ in range(orders):
                # La mayoría de pedidos son de 1-2 unidades; algunos son de tiendas (cajas).
                qty = rng.choices((1, 2, 3, case), (0.62, 0.24, 0.09, 0.05))[0]
                if qty <= stock[home]:
                    exits.append(_exit(rng, index, qty, home, day, "dispatch", trackings, users, user_weights))
                    stock[home] -= qty

            # Mermas: rotura, caducidad o descuadre de recuento (más en electrónica pequeña).
            loss_rate = {"electronics": 0.006, "cosmetics": 0.005, "fashion": 0.003}[create.category]
            if stock[home] > 0 and rng.random() < loss_rate:
                qty = min(stock[home], rng.randint(1, 3))
                exits.append(_exit(rng, index, qty, home, day, "loss", trackings, users, user_weights))
                stock[home] -= qty

            if pending_arrival is None and stock[home] <= reorder_point and day < stop_restock:
                pending_arrival = day + timedelta(days=rng.randint(5, 14))  # plazo del proveedor
                pending_qty = order_up_to - stock[home]

            day += timedelta(days=1)

    return entries, exits


def _entry(rng, index, qty, warehouse, day, counters, users, weights) -> dict:
    kind = rng.choices(("PO", "ASN", "GR"), (0.55, 0.25, 0.20))[0]
    if kind == "GR":
        kind = f"GR-{warehouse}"
    counters[kind] += 1
    year = day.year
    reference = {
        "PO": f"PO-{year}-{counters['PO']:05d}",
        "ASN": f"ASN-{year}-{counters['ASN']:05d}",
    }.get(kind, f"{kind}-{counters.get(kind, 0):04d}")
    data = StockEntryCreate(sku_id=1, quantity=qty, reference=reference, warehouse=warehouse)
    return {
        "sku_index": index,
        **data.model_dump(exclude={"sku_id"}),
        "created_at": _timestamp(rng, day, warehouse),
        "user_uuid": rng.choices(users, weights)[0],
    }


def _exit(rng, index, qty, warehouse, day, exit_type, trackings, users, weights) -> dict:
    tracking = None
    if exit_type == "dispatch":
        _, probs, makers = zip(*CARRIERS[warehouse])
        maker = rng.choices(makers, probs)[0]
        tracking = maker(rng)
        while tracking in trackings:
            tracking = maker(rng)
        trackings.add(tracking)
    data = StockExitCreate(sku_id=1, quantity=qty, exit_type=exit_type, tracking_number=tracking, warehouse=warehouse)
    return {
        "sku_index": index,
        **data.model_dump(exclude={"sku_id"}),
        "created_at": _timestamp(rng, day, warehouse),
        "user_uuid": rng.choices(users, weights)[0],
    }


# =========================================================
# INCIDENCIAS
# =========================================================

# (categoría, plantillas de título, plantillas de descripción, sedes probables, orígenes probables)
INCIDENT_TEMPLATES = [
    (
        "lost_parcel",
        ["Paquete {tracking} sin escaneos desde hace {days} días", "Envío de {brand} perdido en tránsito ({carrier})"],
        [
            "El envío {tracking} de {brand} salió del almacén el {date} con {carrier} y no tiene ningún escaneo desde la recogida. "
            "La cliente final reclama el pedido. Abrir reclamación con el transportista y valorar reenvío.",
            "{carrier} confirma que el bulto {tracking} no aparece en su hub. Contenía {qty} uds de {sku}. {brand} pide reposición urgente.",
        ],
        ("la_warehouse", "zaragoza_warehouse", "la_office", "zaragoza_office"),
        ("customer", "branch"),
    ),
    (
        "delivery_failure",
        ["Entrega fallida: dirección incompleta ({brand})", "{carrier} devuelve {tracking} por destinatario ausente"],
        [
            "Tercer intento de entrega fallido para {tracking}. El destinatario no estaba y {carrier} devuelve el paquete al almacén. "
            "Contactar con {brand} para confirmar dirección y teléfono.",
            "La dirección del pedido de {brand} no incluye número de portal; {carrier} no puede entregar {tracking}.",
        ],
        ("la_office", "zaragoza_office"),
        ("customer", "branch"),
    ),
    (
        "inventory_discrepancy",
        ["Descuadre de stock en {sku}", "Recuento cíclico: faltan {qty} uds de {sku}"],
        [
            "En el recuento cíclico de la ubicación de {sku} ({brand}) aparecen {qty} unidades menos de las que indica el sistema. "
            "Revisar las salidas de la última semana y las recepciones pendientes de ubicar.",
            "La recepción {reference} de {brand} se registró con {qty} uds pero en la estantería hay menos. Posible error de conteo en muelle.",
        ],
        ("la_warehouse", "zaragoza_warehouse"),
        ("branch", "internal"),
    ),
    (
        "carrier_issue",
        ["Recogida de {carrier} no realizada hoy", "{carrier} entrega con retraso los pedidos de {brand}"],
        [
            "{carrier} no ha pasado a recoger la ola de las 17:00. Quedan pendientes los pedidos de {brand} y de otras marcas; "
            "riesgo de incumplir el SLA de envío en 24 h.",
            "Retrasos de 2-3 días en la última milla de {carrier} para envíos de {brand}. Varias consultas de clientes finales por {tracking} y otros.",
        ],
        ("la_warehouse", "zaragoza_warehouse", "central"),
        ("branch", "internal", "customer"),
    ),
    (
        "returns_issue",
        ["Devolución de {brand} sin RMA", "Producto devuelto dañado: {sku}"],
        [
            "Ha llegado al almacén una devolución de {brand} sin número de RMA ni albarán. Contiene {qty} uds de {sku}. "
            "No se puede reintegrar al stock hasta que la marca confirme.",
            "La devolución del pedido {tracking} llega con el embalaje abierto y el producto {sku} usado. {brand} decide si se da de baja como pérdida.",
        ],
        ("la_warehouse", "zaragoza_warehouse"),
        ("customer", "branch"),
    ),
    (
        "warehouse_incident",
        ["Carretilla averiada en el muelle de {warehouse}", "Palé dañado al descargar recepción {reference}"],
        [
            "Durante la descarga de la recepción {reference} de {brand} se volcó un palé. Hay unidades de {sku} con la caja aplastada; "
            "pendiente de clasificar qué se puede vender.",
            "La carretilla del muelle 2 en {warehouse} está fuera de servicio. Las recepciones se descargan a mano y se acumulan retrasos.",
        ],
        ("la_warehouse", "zaragoza_warehouse"),
        ("branch", "internal"),
    ),
    (
        "system_failure",
        ["Etiquetas de {carrier} no se generan", "La integración con la tienda de {brand} no descarga pedidos"],
        [
            "Desde las {hour}:00 la API de {carrier} devuelve error al generar etiquetas. Los pedidos de {brand} se quedan en preparación.",
            "La sincronización de pedidos de {brand} falla desde esta mañana: los pedidos nuevos no llegan al almacén de {warehouse}.",
        ],
        ("central", "la_office", "zaragoza_office"),
        ("internal", "branch"),
    ),
    (
        "client_complaint",
        ["{brand} reclama por retrasos en la preparación", "{brand} pide informe de mermas del trimestre"],
        [
            "{brand} se queja de que los pedidos entrados antes de las 14:00 no salen el mismo día, como dice el contrato. Pide un plan de acción.",
            "La responsable de operaciones de {brand} pide el detalle de las pérdidas de {sku} y su impacto en la facturación.",
        ],
        ("la_office", "zaragoza_office", "central"),
        ("customer",),
    ),
    (
        "other",
        ["Consulta de {brand} sobre tarifas de almacenaje", "Visita de auditoría de {brand} al almacén de {warehouse}"],
        [
            "{brand} pregunta por el coste de almacenaje por palé para la campaña de Navidad y si hay espacio en {warehouse}.",
            "{brand} quiere visitar el almacén de {warehouse} para revisar cómo se preparan sus pedidos. Proponer fecha.",
        ],
        ("central", "la_office", "zaragoza_office"),
        ("customer", "internal"),
    ),
]
WAREHOUSE_BRANCH = {"LA": ("la_warehouse", "la_office"), "ZGZ": ("zaragoza_warehouse", "zaragoza_office")}
WAREHOUSE_NAME = {"LA": "Los Ángeles", "ZGZ": "Zaragoza"}


def build_incidents(rng: random.Random, count: int, skus: list[dict], exits: list[dict], entries: list[dict]) -> list[dict]:
    """Incidencias que citan SKUs, marcas, transportistas y seguimientos reales del seed."""
    dispatches = [e for e in exits if e["exit_type"] == "dispatch"]
    incidents = []
    weights = (14, 12, 10, 16, 12, 8, 6, 8, 4)  # carrier_issue y lost_parcel son lo más habitual
    for _ in range(count):
        category, titles, descriptions, branches, origins = rng.choices(INCIDENT_TEMPLATES, weights)[0]
        dispatch = rng.choice(dispatches)
        sku = skus[dispatch["sku_index"]]
        warehouse = dispatch["warehouse"]
        carrier = next(name for name, _, maker in CARRIERS[warehouse] if _matches_carrier(name, dispatch["tracking_number"]))
        entry = rng.choice(entries)
        created = dispatch["created_at"] + timedelta(days=rng.randint(1, 12), hours=rng.randint(0, 6))
        if created.date() > TODAY:
            created = datetime(TODAY.year, TODAY.month, TODAY.day, 10, tzinfo=timezone.utc)
        values = {
            "tracking": dispatch["tracking_number"],
            "brand": sku["create"].client_name,
            "carrier": carrier,
            "sku": sku["create"].sku,
            "qty": rng.randint(1, 24),
            "days": rng.randint(4, 15),
            "date": dispatch["created_at"].strftime("%d/%m/%Y"),
            "reference": entry["reference"],
            "warehouse": WAREHOUSE_NAME[warehouse],
            "hour": rng.randint(8, 18),
        }
        # La sede es la del almacén del envío si la plantilla lo admite.
        local = [b for b in branches if b in WAREHOUSE_BRANCH[warehouse]]
        branch = rng.choice(local or list(branches))
        age_days = (TODAY - created.date()).days
        # Las antiguas están casi todas cerradas; las recientes, abiertas o en curso.
        if age_days > 30:
            status = rng.choices(("resolved", "discarded", "in_progress", "open"), (0.82, 0.12, 0.04, 0.02))[0]
        else:
            status = rng.choices(("open", "in_progress", "resolved", "discarded"), (0.45, 0.35, 0.15, 0.05))[0]
        updated = created if status == "open" else created + timedelta(days=rng.randint(0, min(20, max(age_days, 0))), hours=rng.randint(1, 8))
        incidents.append(
            {
                "title": rng.choice(titles).format(**values)[:120],
                "description": rng.choice(descriptions).format(**values),
                "category": category,
                "origin": rng.choice(origins),
                "branch": branch,
                "status": status,
                "created_at": created.isoformat(),
                "updated_at": updated.isoformat(),
            }
        )
    return incidents


def _matches_carrier(name: str, tracking: str) -> bool:
    prefixes = {"UPS": "1Z", "USPS": "9400", "OnTrac": "D", "Correos Express": "3230", "DHL Parcel": "JJD"}
    if name in prefixes:
        return tracking.startswith(prefixes[name])
    lengths = {"FedEx": 12, "SEUR": 14, "GLS": 11}
    return len(tracking) == lengths[name] and tracking.isdigit()


# =========================================================
# CONTEO, ESCRITURA Y PURGA
# =========================================================


def counts() -> dict[str, int]:
    with Session(engine) as db:
        result = {
            "sku": db.exec(select(func.count()).select_from(SKU)).one(),
            "stock_entry": db.exec(select(func.count()).select_from(StockEntry)).one(),
            "stock_exit": db.exec(select(func.count()).select_from(StockExit)).one(),
        }
    result["incidents (TinyDB)"] = len(store.get_all_incidents())
    result["incident_embeddings (TinyDB)"] = len(store.get_incident_embeddings())
    result["suppliers (TinyDB)"] = len(store.get_all_suppliers())
    return result


def print_counts(title: str) -> None:
    print(f"\n{title}")
    for table, total in counts().items():
        print(f"  {table:<30} {total:>7}")


def _batches(rows: list[dict], size: int = 2000):
    for start in range(0, len(rows), size):
        yield rows[start:start + size]


def seed_inventory(db: Session, skus: list[dict], entries: list[dict], exits: list[dict]) -> None:
    existing = db.exec(select(func.count()).select_from(SKU).where(SKU.client_name.in_(BRAND_NAMES))).one()
    if existing:
        sys.exit(f"Ya hay {existing} SKUs de las marcas de este seed. Ejecuta antes --purge.")

    # INSERT ... RETURNING por lotes: una ida y vuelta a Supabase por lote, no por fila.
    ids = []
    for batch in _batches([sku["create"].model_dump() for sku in skus]):
        ids += [row.id for row in db.execute(insert(SKU).returning(SKU.id), batch)]

    for model, rows in ((StockEntry, entries), (StockExit, exits)):
        for batch in _batches(rows):
            db.execute(insert(model), [{**{k: v for k, v in row.items() if k != "sku_index"}, "sku_id": ids[row["sku_index"]]} for row in batch])

    # Misma comprobación que la API, sobre los datos aún sin confirmar.
    negative = [(sku_id, w) for sku_id, levels in inventory_service.stock_levels(db, ids).items() for w, units in levels.items() if units < 0]
    if negative:
        db.rollback()
        sys.exit(f"El seed dejaría stock negativo en {negative[:5]}: no se ha escrito nada.")
    db.commit()


def seed_incidents(incidents: list[dict]) -> None:
    for incident in incidents:
        clean, errors = validate_incident_fields(incident)
        if errors:
            sys.exit(f"Incidencia no válida en el seed: {errors}")
        created = store.create_incident({**clean, "created_at": incident["created_at"], "updated_at": incident["updated_at"]})
        perf_seed_incidents_table.insert({"incident_id": created["id"]})


def purge() -> None:
    with Session(engine) as db:
        sku_ids = select(SKU.id).where(SKU.client_name.in_(BRAND_NAMES))
        removed_entries = db.execute(delete(StockEntry).where(StockEntry.sku_id.in_(sku_ids))).rowcount
        removed_exits = db.execute(delete(StockExit).where(StockExit.sku_id.in_(sku_ids))).rowcount
        removed_skus = db.execute(delete(SKU).where(SKU.client_name.in_(BRAND_NAMES))).rowcount
        db.commit()
    print(f"Inventario: borrados {removed_skus} SKUs, {removed_entries} entradas y {removed_exits} salidas.")

    ids = [doc["incident_id"] for doc in perf_seed_incidents_table.all()]
    store.incidents_table.remove(doc_ids=ids)
    store.incident_embeddings_table.remove(store.IncidentQuery.incident_id.one_of(ids))
    perf_seed_incidents_table.truncate()
    print(f"Incidencias: borradas {len(ids)} (y sus embeddings).")


def print_summary(skus, entries, exits, incidents) -> None:
    """Resumen para revisar la calidad de los datos generados (--dry-run)."""
    from collections import Counter

    stock = Counter()
    for row in entries:
        stock[(row["sku_index"], row["warehouse"])] += row["quantity"]
    for row in exits:
        stock[(row["sku_index"], row["warehouse"])] -= row["quantity"]
    home = [stock[(i, sku["create"].warehouse)] for i, sku in enumerate(skus)]
    print("  SKUs por categoría:", dict(Counter(sku["create"].category for sku in skus)))
    print("  SKUs por almacén:  ", dict(Counter(sku["create"].warehouse for sku in skus)))
    print("  Marcas distintas:  ", len({sku["create"].client_name for sku in skus}))
    print("  Stock en su almacén: sin stock", sum(u == 0 for u in home), "| bajo (1-49)", sum(0 < u < 50 for u in home),
          "| OK (50+)", sum(u >= 50 for u in home), "| negativo", sum(u < 0 for u in stock.values()))
    print("  Salidas por tipo:  ", dict(Counter(row["exit_type"] for row in exits)))
    print("  Movimientos por mes:", dict(sorted(Counter(r["created_at"].strftime("%Y-%m") for r in entries + exits).items())))
    print("  Incidencias por categoría:", dict(Counter(i["category"] for i in incidents)))
    print("  Incidencias por estado:   ", dict(Counter(i["status"] for i in incidents)))
    print("  Ejemplos de SKU:", [sku["create"].sku + " · " + sku["create"].name for sku in skus[:4]])
    print("  Ejemplo de entrada:", {k: str(v) for k, v in entries[0].items()})
    print("  Ejemplo de salida: ", {k: str(v) for k, v in exits[0].items()})
    print("  Ejemplo de incidencia:", incidents[0])


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed de volumen para medir el rendimiento de la API.")
    parser.add_argument("--skus", type=int, default=1000, help="Máximo de SKUs (por defecto 1000; con las cuotas por categoría el catálogo da 753).")
    parser.add_argument("--incidents", type=int, default=1200, help="Incidencias a crear (por defecto 1200).")
    parser.add_argument("--no-embeddings", action="store_true", help="No calcular ahora los embeddings de las incidencias.")
    parser.add_argument("--dry-run", action="store_true", help="Generar los datos y resumirlos sin escribir nada.")
    parser.add_argument("--counts", action="store_true", help="Solo mostrar el número de filas por tabla.")
    parser.add_argument("--purge", action="store_true", help="Borrar todo lo que creó este seed.")
    args = parser.parse_args()

    create_db_and_tables()
    if args.counts:
        print_counts("Filas por tabla:")
        return
    if args.purge:
        print_counts("Antes de purgar:")
        purge()
        print_counts("Después de purgar:")
        return

    users = [user["id"] for user in user_service.list_users() if user["is_active"]]
    if not users:
        sys.exit("No hay usuarios activos en TinyDB a los que atribuir los movimientos.")
    if perf_seed_incidents_table.all() and not args.dry_run:
        sys.exit("Las incidencias de este seed ya existen. Ejecuta antes --purge.")

    print_counts("Antes del seed:")
    rng = random.Random(RANDOM_SEED)
    skus = build_skus(rng, args.skus)
    entries, exits = simulate(rng, skus, users)
    incidents = build_incidents(rng, args.incidents, skus, exits, entries)
    print(f"\nGenerado: {len(skus)} SKUs, {len(entries)} entradas, {len(exits)} salidas, {len(incidents)} incidencias.")
    if args.dry_run:
        # Nada de lo anterior ha escrito en ninguna base de datos.
        print_summary(skus, entries, exits, incidents)
        return

    with Session(engine) as db:
        seed_inventory(db, skus, entries, exits)
    print("Inventario escrito en Supabase.")
    seed_incidents(incidents)
    print("Incidencias escritas en TinyDB.")

    if not args.no_embeddings:
        from services.api import incident_service

        print("Calculando embeddings de las incidencias nuevas (la primera vez puede tardar un par de minutos)...")
        print(f"  {incident_service.ensure_index()} embeddings calculados.")

    print_counts("Después del seed:")


if __name__ == "__main__":
    main()
