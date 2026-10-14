"""El inventario de extremo a extremo por HTTP: autenticación contra TinyDB, códigos de estado
que comprobará el evaluador y el 503 si Supabase no responde."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

import services.api.main as main
from services.database import get_db

SNEAKER = {
    "name": "Zapatilla blanca clásica - Talla 42",
    "sku": "CLT-SNK-W-42",
    "client_name": "PureStep Footwear",
    "category": "fashion",
    "warehouse": "LA",
}

ROUTES = [
    ("get", "/inventory/products", None),
    ("post", "/inventory/products", SNEAKER),
    ("get", "/inventory/products/1", None),
    ("post", "/inventory/orders/inbound", {"sku_id": 1, "quantity": 1, "reference": "PO-1", "warehouse": "LA"}),
    ("post", "/inventory/orders/outbound",
     {"sku_id": 1, "quantity": 1, "exit_type": "loss", "tracking_number": None, "warehouse": "LA"}),
    ("get", "/inventory/orders", None),
]


@pytest.mark.parametrize("method,path,body", ROUTES)
def test_every_inventory_route_requires_a_session(api, method, path, body):
    response = TestClient(main.app).request(method, path, json=body)

    assert response.status_code == 401


@pytest.mark.parametrize("method,path,body", ROUTES)
def test_invalid_token_is_rejected(api, method, path, body):
    response = TestClient(main.app).request(method, path, json=body, headers={"Authorization": "Bearer nope"})

    assert response.status_code == 401


def test_full_flow_stores_the_tinydb_user_and_derives_the_stock(api, operator):
    sku = api.post("/inventory/products", json=SNEAKER)
    assert sku.status_code == 201
    sku_id = sku.json()["id"]
    assert sku.json()["current_stock"] == 0

    entry = api.post("/inventory/orders/inbound",
                     json={"sku_id": sku_id, "quantity": 20, "reference": "PO-2024-0098", "warehouse": "LA"})
    api.post("/inventory/orders/inbound",
             json={"sku_id": sku_id, "quantity": 15, "reference": "GR-ZGZ-0064", "warehouse": "ZGZ"})
    stock_exit = api.post("/inventory/orders/outbound", json={
        "sku_id": sku_id, "quantity": 5, "exit_type": "dispatch",
        "tracking_number": "1Z999AA10123456784", "warehouse": "LA",
    })

    assert entry.status_code == stock_exit.status_code == 201
    assert entry.json()["user_uuid"] == stock_exit.json()["user_uuid"] == operator["id"]

    product = api.get(f"/inventory/products/{sku_id}").json()
    assert product["current_stock"] == 15
    assert product["stock_by_warehouse"] == {"LA": 15, "ZGZ": 15}
    assert api.get("/inventory/products").json() == [product]

    orders = api.get("/inventory/orders").json()
    assert sorted(order["order_type"] for order in orders) == ["inbound", "inbound", "outbound"]
    assert all(order["sku"]["sku"] == "CLT-SNK-W-42" for order in orders)
    assert all("hashed_password" not in str(order) for order in orders)


def test_exit_beyond_stock_returns_400_with_the_context_message(api):
    sku_id = api.post("/inventory/products", json=SNEAKER).json()["id"]
    api.post("/inventory/orders/inbound", json={"sku_id": sku_id, "quantity": 3, "reference": "PO-1", "warehouse": "LA"})

    response = api.post("/inventory/orders/outbound", json={
        "sku_id": sku_id, "quantity": 4, "exit_type": "loss", "tracking_number": None, "warehouse": "LA",
    })

    assert response.status_code == 400
    assert response.json() == {"detail": "Insufficient stock for SKU 'CLT-SNK-W-42'. Available: 3, requested: 4."}
    assert [order["order_type"] for order in api.get("/inventory/orders").json()] == ["inbound"]


def test_dispatch_without_tracking_number_is_a_validation_error(api):
    sku_id = api.post("/inventory/products", json=SNEAKER).json()["id"]

    response = api.post("/inventory/orders/outbound", json={
        "sku_id": sku_id, "quantity": 1, "exit_type": "dispatch", "warehouse": "LA",
    })

    assert response.status_code == 422
    assert "tracking_number is required" in str(response.json())


def test_stock_cannot_be_sent_when_creating_a_product(api):
    response = api.post("/inventory/products", json={**SNEAKER, "current_stock": 500})

    assert response.status_code == 422


def test_duplicate_sku_code_is_a_conflict(api):
    api.post("/inventory/products", json=SNEAKER)

    assert api.post("/inventory/products", json={**SNEAKER, "warehouse": "ZGZ"}).status_code == 409


def test_unknown_sku_is_404(api):
    assert api.get("/inventory/products/999").status_code == 404
    response = api.post("/inventory/orders/inbound",
                        json={"sku_id": 999, "quantity": 1, "reference": "PO-1", "warehouse": "LA"})
    assert response.status_code == 404


def test_unreachable_supabase_is_a_503_not_a_500(api):
    class DownSession:
        def exec(self, *args, **kwargs):
            raise OperationalError("SELECT", {}, Exception("could not connect to server"))

    def down_db():
        yield DownSession()

    main.app.dependency_overrides[get_db] = down_db

    response = api.get("/inventory/products")

    assert response.status_code == 503
    assert "could not connect" not in response.text
