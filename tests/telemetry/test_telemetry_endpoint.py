"""Stub POST /telemetry/events (hito 15): acepta lotes con el envelope de la Fase 1, escribe en
el log cuántos eventos llegan y de qué tipo, y responde {"received": N} sin guardar nada."""

import json
import logging
import uuid

import pytest

from services import telemetry
from services.api import config


def event(event_type="page_viewed", **overrides) -> dict:
    base = {
        "eventId": str(uuid.uuid4()),
        "timestamp": "2026-10-27T09:15:02.481Z",
        "sessionId": str(uuid.uuid4()),
        "userId": str(uuid.uuid4()),
        "event_type": event_type,
        "schemaVersion": "1.0.0",
        "requestId": str(uuid.uuid4()),
        "source": "backoffice_web",
        "environment": "development",
        "properties": {"page_route": "/inventory/products", "section": "inventory", "previous_route": None},
    }
    return {**base, **overrides}


@pytest.fixture
def telemetry_log(caplog):
    # El logger "api" no propaga (main.py le pone su propio handler): se engancha el de caplog.
    logger = logging.getLogger("api.telemetry")
    logger.addHandler(caplog.handler)
    caplog.set_level(logging.INFO, logger="api.telemetry")
    yield caplog
    logger.removeHandler(caplog.handler)


# =========================================================
# Contrato del stub
# =========================================================


def test_a_batch_is_received_and_counted(anon_client):
    response = anon_client.post("/telemetry/events", json={"events": [event(), event()]})

    assert response.status_code == 200
    assert response.json() == {"received": 2}


def test_it_logs_how_many_events_arrive_and_their_types(anon_client, telemetry_log):
    other = event("frontend_error_captured", properties={
        "page_route": "/", "error_source": "window_error", "error_name": "TypeError",
        "error_fingerprint": "0123456789abcdef", "occurrences": 1,
    })
    anon_client.post("/telemetry/events", json={"events": [event(), other]})

    assert "telemetry batch received=2 valid=2 source=backoffice_web event_types=page_viewed,frontend_error_captured" in telemetry_log.text


def test_it_needs_no_jwt_because_send_beacon_cannot_send_one(anon_client):
    assert anon_client.post("/telemetry/events", json={"events": [event()]}).status_code == 200


def test_a_send_beacon_body_sent_as_text_plain_is_accepted(anon_client):
    response = anon_client.post(
        "/telemetry/events", content=json.dumps({"events": [event()]}), headers={"Content-Type": "text/plain;charset=UTF-8"}
    )

    assert response.json() == {"received": 1}


@pytest.mark.parametrize(
    "bad",
    [
        {"eventId": "not-a-uuid"},
        {"timestamp": "2026-10-27 09:15:02"},
        {"event_type": "PageViewed"},
        {"schemaVersion": "1"},
        {"source": "mobile_app"},
        {"extra_top_level_key": "x"},
    ],
)
def test_a_malformed_envelope_is_rejected_without_echoing_it(anon_client, bad):
    response = anon_client.post("/telemetry/events", json={"events": [event(**bad)]})

    assert response.status_code == 422
    assert all("input" not in item for item in response.json()["detail"])


def test_every_envelope_field_is_required(anon_client):
    for field in ("eventId", "timestamp", "sessionId", "userId", "event_type", "schemaVersion", "requestId", "properties"):
        incomplete = event()
        del incomplete[field]
        assert anon_client.post("/telemetry/events", json={"events": [incomplete]}).status_code == 422, field


@pytest.mark.parametrize("events", [[], [event() for _ in range(telemetry.MAX_BATCH_EVENTS + 1)]])
def test_empty_or_oversized_batches_are_rejected(anon_client, events):
    assert anon_client.post("/telemetry/events", json={"events": events}).status_code == 422


def test_an_unreadable_body_is_rejected(anon_client):
    assert anon_client.post("/telemetry/events", content=b"not json", headers={"Content-Type": "text/plain"}).status_code == 422


def test_an_event_outside_its_allowlist_is_logged_as_a_violation_without_its_value(anon_client, telemetry_log):
    leaky = event(properties={"page_route": "/inventory/products", "section": "inventory", "previous_route": None, "email": "ana@trackflow.com"})

    response = anon_client.post("/telemetry/events", json={"events": [leaky]})

    assert response.json() == {"received": 1}
    assert "telemetry_schema_violation event_type=page_viewed" in telemetry_log.text
    assert "ana@trackflow.com" not in telemetry_log.text


# =========================================================
# Correlación y configuración
# =========================================================


def test_the_request_id_sent_by_the_backoffice_comes_back_in_the_response(anon_client):
    request_id = str(uuid.uuid4())

    response = anon_client.get("/", headers={"X-Request-Id": request_id})

    assert response.headers["X-Request-Id"] == request_id


def test_a_request_without_a_valid_request_id_gets_a_new_one(anon_client):
    response = anon_client.get("/", headers={"X-Request-Id": "<script>"})

    assert telemetry._uuid_or_none(response.headers["X-Request-Id"])


def test_the_backend_declares_the_telemetry_endpoint_in_its_configuration():
    assert config.TELEMETRY_ENDPOINT.endswith("/telemetry/events")


def test_the_schema_version_comes_from_event_schemas_json():
    assert telemetry.schema_version("page_viewed") == "1.0.0"
    assert telemetry.schema_version("login_failed") == "2.0.0"


@pytest.mark.parametrize(
    ("name", "slug"),
    [("PureStep Footwear", "purestep_footwear"), ("GlowLab Cosmetics", "glowlab_cosmetics"), ("Café & Moda, S.L.", "cafe_moda_s_l")],
)
def test_client_id_is_the_deterministic_slug_of_the_plan(name, slug):
    assert telemetry.client_id(name) == slug
