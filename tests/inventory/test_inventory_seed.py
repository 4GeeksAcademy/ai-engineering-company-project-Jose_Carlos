"""Datos semilla de CONTEXT-9 (services/seed_inventory.py)."""

from collections import Counter

from sqlmodel import select

from services import inventory_service, seed_inventory
from services.models import SKU, StockEntry, StockExit


def _net_from_seed_data():
    net = Counter()
    for code, quantity, _, warehouse in seed_inventory.ENTRIES:
        net[(code, warehouse)] += quantity
    for code, quantity, _, _, warehouse in seed_inventory.EXITS:
        net[(code, warehouse)] -= quantity
    return net


def test_seed_meets_the_context_minimums():
    assert len(seed_inventory.SKUS) >= 6
    assert len(seed_inventory.ENTRIES) >= 4
    assert len(seed_inventory.EXITS) >= 3

    entries_per_sku = Counter(code for code, *_ in seed_inventory.ENTRIES)
    assert any(count >= 2 for count in entries_per_sku.values())
    assert {warehouse for *_, warehouse in seed_inventory.ENTRIES} == {"LA", "ZGZ"}

    exit_types = {(exit_type, tracking is None) for _, _, exit_type, tracking, _ in seed_inventory.EXITS}
    assert ("dispatch", False) in exit_types
    assert ("loss", True) in exit_types


def test_expected_stock_is_exactly_entries_minus_exits():
    net = _net_from_seed_data()

    for code, by_warehouse in seed_inventory.EXPECTED_STOCK.items():
        for warehouse, units in by_warehouse.items():
            assert units == net[(code, warehouse)], (code, warehouse)
            assert units >= 0


def test_seed_populates_the_inventory_and_the_stock_matches(db, operator):
    created = seed_inventory.seed(db, operator["id"])

    assert created == {
        "skus": len(seed_inventory.SKUS),
        "entries": len(seed_inventory.ENTRIES),
        "exits": len(seed_inventory.EXITS),
    }
    stock = {sku.sku: sku.stock_by_warehouse for sku in inventory_service.list_skus(db)}
    assert stock == seed_inventory.EXPECTED_STOCK


def test_seeded_movements_belong_to_the_tinydb_user(db, operator):
    seed_inventory.seed(db, operator["id"])

    owners = {row.user_uuid for row in db.exec(select(StockEntry)).all()}
    owners |= {row.user_uuid for row in db.exec(select(StockExit)).all()}
    assert owners == {operator["id"]}


def test_seed_can_run_twice_without_duplicating_stock(db, operator):
    seed_inventory.seed(db, operator["id"])

    again = seed_inventory.seed(db, operator["id"])

    assert again == {"skus": 0, "entries": 0, "exits": 0}
    assert len(db.exec(select(SKU)).all()) == len(seed_inventory.SKUS)
    stock = {sku.sku: sku.stock_by_warehouse for sku in inventory_service.list_skus(db)}
    assert stock == seed_inventory.EXPECTED_STOCK


def test_seeded_products_endpoint_reflects_the_net_stock(api, engine, operator):
    from sqlmodel import Session

    with Session(engine) as db:
        seed_inventory.seed(db, operator["id"])

    products = {product["sku"]: product for product in api.get("/inventory/products").json()}

    assert products["CLT-SNK-W-42"]["current_stock"] == 170
    assert products["TEC-EAR-001"]["current_stock"] == 48
    assert products["TEC-EAR-001"]["stock_by_warehouse"] == {"LA": 48, "ZGZ": 15}
    assert products["CSM-SRM-030"]["current_stock"] == 155
