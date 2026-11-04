"""Telemetría que emite la API de inventario (hito 15): stock_threshold_triggered,
inventory_discrepancy_detected y direct_stock_edit_rejected, más el `stock_after` que el
backoffice necesita para sus eventos de entrada y salida."""

import uuid

import pytest
from fastapi.testclient import TestClient

import services.api.main as main
from services import telemetry
from services.api import user_service
from services.api.security import create_access_token
from services.api.user_models import UserRole


@pytest.fixture
def events(monkeypatch):
    """Eventos que la API emite (los que llegarían al stub), en orden."""
    emitted = []
    original = telemetry.record_events

    def capture(batch):
        emitted.extend(event.model_dump() for event in batch)
        return original(batch)

    monkeypatch.setattr(telemetry, "record_events", capture)
    return emitted


def of_type(emitted, event_type):
    return [event for event in emitted if event["event_type"] == event_type]


@pytest.fixture
def manager_api(api):
    """El mismo cliente, autenticado como responsable (puede fijar umbrales)."""
    manager, _ = user_service.create_user(f"jefa-{uuid.uuid4().hex[:8]}@trackflow.com", "s3cret-password", role=UserRole.MANAGER)
    return TestClient(main.app, headers={"Authorization": f"Bearer {create_access_token(manager['id'])}"})


def ship(api, sku, quantity, exit_type="dispatch", **headers):
    body = {"sku_id": sku.id, "quantity": quantity, "exit_type": exit_type, "warehouse": sku.warehouse,
            "tracking_number": "1Z999AA10123456784" if exit_type == "dispatch" else None}
    return api.post("/inventory/orders/outbound", json=body, headers=headers)


# =========================================================
# stock_after en las altas
# =========================================================


def test_inbound_and_outbound_responses_carry_the_stock_they_leave(api, sneaker):
    entry = api.post("/inventory/orders/inbound", json={"sku_id": sneaker.id, "quantity": 100, "reference": "PO-1", "warehouse": "LA"})
    exit_ = ship(api, sneaker, 30)

    assert entry.status_code == 201 and entry.json()["stock_after"] == 100
    assert exit_.status_code == 201 and exit_.json()["stock_after"] == 70
    assert exit_.json()["sku"]["category"] == "fashion"


# =========================================================
# stock_threshold_triggered (PR-1)
# =========================================================


def test_only_managers_and_admins_can_set_a_threshold(api, manager_api, sneaker):
    body = {"sku_id": sneaker.id, "warehouse": "LA", "min_stock": 50}

    assert api.post("/inventory/thresholds", json=body).status_code == 403
    assert manager_api.post("/inventory/thresholds", json=body).status_code == 200
    assert api.get("/inventory/thresholds").json()[0]["min_stock"] == 50


def test_setting_a_threshold_again_replaces_it(manager_api, sneaker):
    for min_stock in (50, 20):
        manager_api.post("/inventory/thresholds", json={"sku_id": sneaker.id, "warehouse": "LA", "min_stock": min_stock})

    assert [t["min_stock"] for t in manager_api.get("/inventory/thresholds").json()] == [20]


def test_crossing_the_minimum_emits_one_event_and_rearms_after_restocking(api, manager_api, sneaker, receive, events):
    receive(sneaker, 100)
    manager_api.post("/inventory/thresholds", json={"sku_id": sneaker.id, "warehouse": "LA", "min_stock": 50})

    ship(api, sneaker, 40)  # 100 → 60: sigue por encima
    ship(api, sneaker, 20)  # 60 → 40: cruza
    ship(api, sneaker, 10)  # 40 → 30: ya estaba por debajo, no se repite
    receive(sneaker, 70)    # 30 → 100: se rearma
    ship(api, sneaker, 60, exit_type="loss")  # 100 → 40: cruza otra vez, por pérdida

    crossings = of_type(events, "stock_threshold_triggered")
    assert [(e["properties"]["stock_before"], e["properties"]["quantity"]) for e in crossings] == [(60, 40), (100, 40)]
    assert [e["properties"]["trigger_order_type"] for e in crossings] == ["dispatch", "loss"]
    assert crossings[0]["properties"] | {"trigger_order_id": None} == {
        "warehouse": "los_angeles", "country": "US", "client_id": "purestep_footwear", "product_id": "CLT-SNK-W-42",
        "product_category": "fashion", "quantity": 40, "min_stock": 50, "stock_before": 60,
        "trigger_order_type": "dispatch", "trigger_order_id": None,
    }
    assert all(telemetry.schema_violations(event) == [] for event in crossings)


def test_the_event_carries_the_correlation_ids_of_the_request(api, manager_api, sneaker, receive, events):
    receive(sneaker, 10)
    manager_api.post("/inventory/thresholds", json={"sku_id": sneaker.id, "warehouse": "LA", "min_stock": 5})
    request_id, session_id = str(uuid.uuid4()), str(uuid.uuid4())

    ship(api, sneaker, 8, **{"X-Request-Id": request_id, "X-Session-Id": session_id})

    [crossing] = of_type(events, "stock_threshold_triggered")
    assert (crossing["requestId"], crossing["sessionId"], crossing["source"]) == (request_id, session_id, "api")


def test_a_sku_without_threshold_never_emits(api, sneaker, receive, events):
    receive(sneaker, 10)
    ship(api, sneaker, 10)

    assert of_type(events, "stock_threshold_triggered") == []


def test_a_rejected_exit_does_not_emit(api, manager_api, sneaker, receive, events):
    receive(sneaker, 10)
    manager_api.post("/inventory/thresholds", json={"sku_id": sneaker.id, "warehouse": "LA", "min_stock": 5})

    assert ship(api, sneaker, 11).status_code == 400
    assert events == []


# =========================================================
# inventory_discrepancy_detected (PR-2)
# =========================================================


def test_a_count_that_does_not_match_emits_a_discrepancy(api, sneaker, receive, events):
    receive(sneaker, 48)

    response = api.post("/inventory/counts", json={"sku_id": sneaker.id, "warehouse": "LA", "counted_quantity": 46})

    assert response.status_code == 201
    assert (response.json()["system_quantity"], response.json()["difference"]) == (48, -2)
    [discrepancy] = of_type(events, "inventory_discrepancy_detected")
    assert discrepancy["properties"] | {"count_id": None} == {
        "warehouse": "los_angeles", "country": "US", "client_id": "purestep_footwear", "product_id": "CLT-SNK-W-42",
        "product_category": "fashion", "quantity": 2, "system_quantity": 48, "counted_quantity": 46,
        "difference": -2, "count_type": "cycle_count", "count_id": None,
    }
    assert telemetry.schema_violations(discrepancy) == []


def test_a_count_that_matches_is_stored_but_emits_nothing(api, sneaker, receive, events):
    receive(sneaker, 48)

    api.post("/inventory/counts", json={"sku_id": sneaker.id, "warehouse": "LA", "counted_quantity": 48, "count_type": "full_audit"})

    assert events == []
    assert api.get("/inventory/counts").json()[0]["difference"] == 0


def test_a_count_never_changes_the_stock(api, sneaker, receive):
    receive(sneaker, 48)
    api.post("/inventory/counts", json={"sku_id": sneaker.id, "warehouse": "LA", "counted_quantity": 10})

    assert api.get(f"/inventory/products/{sneaker.id}").json()["current_stock"] == 48


# =========================================================
# direct_stock_edit_rejected
# =========================================================


@pytest.mark.parametrize("method", ["put", "patch", "delete"])
def test_editing_a_sku_directly_is_rejected_and_emitted(api, sneaker, events, method):
    response = api.request(method.upper(), f"/inventory/products/{sneaker.id}", json={"current_stock": 500})

    assert response.status_code == 405
    [attempt] = of_type(events, "direct_stock_edit_rejected")
    assert attempt["properties"] == {
        "warehouse": "los_angeles", "country": "US", "client_id": "purestep_footwear", "product_id": "CLT-SNK-W-42",
        "product_category": "fashion", "quantity": 500, "rejection_type": "method_not_allowed",
        "http_method": method.upper(), "api_route": "/inventory/products/{sku_id}", "rejected_fields": [],
        "user_role": "user", "client_channel": "direct_api",
    }
    assert telemetry.schema_violations(attempt) == []


def test_sending_a_stock_field_in_a_movement_is_rejected_and_emitted(api, sneaker, events):
    body = {"sku_id": sneaker.id, "quantity": 5, "reference": "PO-1", "warehouse": "LA", "current_stock": 999}

    response = api.post("/inventory/orders/inbound", json=body, headers={"X-Session-Id": str(uuid.uuid4())})

    assert response.status_code == 422
    [attempt] = of_type(events, "direct_stock_edit_rejected")
    props = attempt["properties"]
    assert (props["rejection_type"], props["rejected_fields"], props["quantity"]) == ("forbidden_stock_field", ["current_stock"], 999)
    assert (props["api_route"], props["product_id"], props["client_channel"]) == ("/inventory/orders/inbound", "CLT-SNK-W-42", "backoffice_web")


def test_creating_a_sku_with_stock_is_rejected_and_emitted_with_the_body_data(api, events):
    body = {"name": "Sérum", "sku": "CSM-SRM-030", "client_name": "GlowLab Cosmetics", "category": "cosmetics",
            "warehouse": "ZGZ", "quantity": 200}

    assert api.post("/inventory/products", json=body).status_code == 422
    [attempt] = of_type(events, "direct_stock_edit_rejected")
    assert (attempt["properties"]["client_id"], attempt["properties"]["warehouse"], attempt["properties"]["rejected_fields"]) == (
        "glowlab_cosmetics", "zaragoza", ["quantity"])


def test_an_unknown_sku_still_emits_with_null_inventory_fields(api, events):
    api.put("/inventory/products/9999", json={})

    [attempt] = of_type(events, "direct_stock_edit_rejected")
    assert attempt["properties"]["product_id"] is None and attempt["properties"]["quantity"] is None
    assert telemetry.schema_violations(attempt) == []


def test_an_ordinary_validation_error_is_not_a_direct_edit(api, sneaker, events):
    assert api.post("/inventory/orders/inbound", json={"sku_id": sneaker.id, "warehouse": "LA"}).status_code == 422
    assert events == []


def test_an_unauthenticated_attempt_is_not_attributed_to_the_staff(anon_client, sneaker, events):
    anon_client.put(f"/inventory/products/{sneaker.id}", json={"current_stock": 1})

    assert events == []
