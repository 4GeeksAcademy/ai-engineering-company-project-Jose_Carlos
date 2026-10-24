"""GET /inventory/products y /inventory/orders con caché: HIT / MISS, caducidad e invalidación
por escrituras."""

import uuid

import pytest
from fastapi.testclient import TestClient

import services.api.main as main
from services import inventory_service
from services.api import cache, user_service
from services.api.security import create_access_token
from services.routers.inventory import INVENTORY_ORDERS_TTL_SECONDS, INVENTORY_PRODUCTS_TTL_SECONDS


@pytest.fixture
def clock(monkeypatch):
    class Clock:
        now = 1000.0

    monkeypatch.setattr(cache, "_clock", lambda: Clock.now)
    return Clock


@pytest.fixture
def sku_queries(monkeypatch):
    """Cuántas veces se ha calculado el catálogo de verdad contra la base de datos."""
    calls = []
    original = inventory_service.list_skus
    monkeypatch.setattr(inventory_service, "list_skus", lambda db: calls.append(1) or original(db))
    return calls


def stock_of(api, sku_id):
    product = next(p for p in api.get("/inventory/products").json() if p["id"] == sku_id)
    return product["current_stock"]


def test_second_read_is_served_from_the_cache(api, sneaker, receive, sku_queries, clock):
    receive(sneaker, 10)

    first = api.get("/inventory/products")
    second = api.get("/inventory/products")

    assert first.status_code == second.status_code == 200
    assert second.json() == first.json()
    assert len(sku_queries) == 1  # MISS + HIT: una sola consulta


def test_cached_catalog_expires_after_the_ttl(api, sneaker, receive, sku_queries, clock):
    api.get("/inventory/products")

    clock.now += INVENTORY_PRODUCTS_TTL_SECONDS - 1
    api.get("/inventory/products")
    assert len(sku_queries) == 1

    clock.now += 1
    api.get("/inventory/products")
    assert len(sku_queries) == 2


@pytest.mark.parametrize(
    "path,body,expected_stock",
    [
        ("/inventory/orders/inbound", {"quantity": 5, "reference": "PO-9", "warehouse": "LA"}, 15),
        ("/inventory/orders/outbound", {"quantity": 5, "exit_type": "loss", "tracking_number": None, "warehouse": "LA"}, 5),
    ],
    ids=["inbound", "outbound"],
)
def test_stock_movement_invalidates_and_next_read_is_fresh(api, sneaker, receive, clock, path, body, expected_stock):
    receive(sneaker, 10)
    assert stock_of(api, sneaker.id) == 10  # queda cacheado

    assert api.post(path, json={"sku_id": sneaker.id, **body}).status_code == 201

    assert stock_of(api, sneaker.id) == expected_stock  # dato nuevo, sin esperar al TTL


def test_new_product_appears_without_waiting_for_the_ttl(api, sneaker, clock):
    assert len(api.get("/inventory/products").json()) == 1

    created = api.post(
        "/inventory/products",
        json={"name": "Zapatilla negra - Talla 40", "sku": "CLT-SNK-B-40", "client_name": "PureStep Footwear",
              "category": "fashion", "warehouse": "ZGZ"},
    )

    assert created.status_code == 201
    assert [p["sku"] for p in api.get("/inventory/products").json()] == ["CLT-SNK-W-42", "CLT-SNK-B-40"]


def test_rejected_exit_does_not_invalidate(api, sneaker, receive, sku_queries, clock):
    receive(sneaker, 3)
    api.get("/inventory/products")

    rejected = api.post(
        "/inventory/orders/outbound",
        json={"sku_id": sneaker.id, "quantity": 50, "exit_type": "loss", "tracking_number": None, "warehouse": "LA"},
    )
    api.get("/inventory/products")

    assert rejected.status_code == 400
    assert len(sku_queries) == 1  # nada ha cambiado: sigue siendo un HIT


def test_cached_catalog_still_requires_a_session(api, sneaker, clock):
    # La autenticación es una dependencia del router y se ejecuta antes de mirar la caché:
    # una respuesta cacheada nunca llega a quien no ha iniciado sesión.
    assert api.get("/inventory/products").status_code == 200

    assert TestClient(main.app).get("/inventory/products").status_code == 401


def test_every_user_with_a_session_gets_the_same_shared_catalog(api, sneaker, sku_queries, clock):
    # El inventario no depende de quién lo consulta: la clave no lleva usuario y otro
    # operario reutiliza la entrada (por eso es seguro compartirla).
    other, _ = user_service.create_user(f"operario-{uuid.uuid4().hex[:8]}@trackflow.com", "s3cret-password")
    other_api = TestClient(main.app, headers={"Authorization": f"Bearer {create_access_token(other['id'])}"})

    first = api.get("/inventory/products").json()
    second = other_api.get("/inventory/products").json()

    assert first == second
    assert len(sku_queries) == 1


# =========================================================
# Histórico de movimientos
# =========================================================


def test_orders_history_is_cached_until_its_ttl(api, sneaker, receive, monkeypatch, clock):
    calls = []
    original = inventory_service.list_orders
    monkeypatch.setattr(inventory_service, "list_orders", lambda db: calls.append(1) or original(db))
    receive(sneaker, 10)

    api.get("/inventory/orders")
    api.get("/inventory/orders")
    assert len(calls) == 1

    clock.now += INVENTORY_ORDERS_TTL_SECONDS
    api.get("/inventory/orders")
    assert len(calls) == 2


def test_new_movement_appears_in_the_cached_history_at_once(api, sneaker, receive, clock):
    receive(sneaker, 10)
    assert len(api.get("/inventory/orders").json()) == 1

    api.post(
        "/inventory/orders/outbound",
        json={"sku_id": sneaker.id, "quantity": 2, "exit_type": "loss", "tracking_number": None, "warehouse": "LA"},
    )

    orders = api.get("/inventory/orders").json()
    assert [order["order_type"] for order in orders] == ["outbound", "inbound"]
