"""POST /telemetry/events con persistencia (hito 16): valida cada evento por separado contra
TelemetryEvent y su allowlist, guarda los válidos en telemetry_events con un único INSERT y
responde {"received", "stored", "rejected"}. Misma URL y mismo envelope que el stub del hito 15."""

import inspect
import json
import logging
import uuid

import pytest
from sqlalchemy import event as sa_event, select
from sqlalchemy.exc import OperationalError
from sqlmodel import Session

from services import telemetry
from services.api import config
from services.routers import telemetry as telemetry_router
from services.telemetry_models import TelemetryEventRecord


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


INBOUND_PROPERTIES = {
    "warehouse": "zaragoza", "country": "ES", "client_id": "glowlab_cosmetics", "product_id": "GLW-SRM-30",
    "product_category": "cosmetics", "quantity": 40, "inbound_order_id": 17, "stock_after": 120,
}

DIRECT_EDIT_PROPERTIES = {
    "warehouse": None, "country": None, "client_id": None, "product_id": None, "product_category": None, "quantity": None,
    "rejection_type": "method_not_allowed", "http_method": "PUT", "api_route": "/inventory/products/{sku_id}",
    "rejected_fields": [], "user_role": "user", "client_channel": "direct_api",
}


@pytest.fixture
def telemetry_log(caplog):
    # El logger "api" no propaga (main.py le pone su propio handler): se engancha el de caplog.
    logger = logging.getLogger("api.telemetry")
    logger.addHandler(caplog.handler)
    caplog.set_level(logging.INFO, logger="api.telemetry")
    yield caplog
    logger.removeHandler(caplog.handler)


def rows(engine) -> list[TelemetryEventRecord]:
    with Session(engine) as session:
        return list(session.exec(select(TelemetryEventRecord)).scalars())


def stored_ids(engine) -> set[str]:
    return {str(row.id) for row in rows(engine)}


@pytest.fixture
def statements(telemetry_store):
    """Sentencias SQL que llegan a la base de telemetría: (sql, executemany)."""
    seen = []

    def record(conn, cursor, statement, parameters, context, executemany):
        seen.append((statement, executemany))

    sa_event.listen(telemetry_store, "before_cursor_execute", record)
    yield seen
    sa_event.remove(telemetry_store, "before_cursor_execute", record)


def inserts(statements) -> list[tuple[str, bool]]:
    return [item for item in statements if item[0].lstrip().upper().startswith("INSERT INTO TELEMETRY_EVENTS")]


# =========================================================
# Contrato: received / stored / rejected
# =========================================================


def test_a_valid_batch_is_stored_and_counted(anon_client, telemetry_store):
    batch = [event(), event()]

    response = anon_client.post("/telemetry/events", json={"events": batch})

    assert response.status_code == 200
    assert response.json() == {"received": 2, "stored": 2, "rejected": 0}
    assert stored_ids(telemetry_store) == {item["eventId"] for item in batch}


def test_a_mixed_batch_stores_the_valid_events_and_rejects_the_rest_individually(anon_client, telemetry_store):
    good = [event(), event("inbound_order_created", properties=INBOUND_PROPERTIES)]
    bad_envelope = event(eventId="not-a-uuid")
    outside_allowlist = event(properties={"page_route": "/", "section": "dashboard", "previous_route": None, "email": "ana@trackflow.com"})
    not_an_object = "page_viewed"

    response = anon_client.post("/telemetry/events", json={"events": [good[0], bad_envelope, outside_allowlist, not_an_object, good[1]]})

    # 200 y no 422: el TelemetryService solo mira el código, y un 4xx le haría tirar también los válidos.
    assert response.status_code == 200
    assert response.json() == {"received": 5, "stored": 2, "rejected": 3}
    assert stored_ids(telemetry_store) == {item["eventId"] for item in good}


def test_a_batch_where_every_event_is_invalid_still_answers_200(anon_client, telemetry_store):
    response = anon_client.post("/telemetry/events", json={"events": [event(source="mobile_app"), {}]})

    assert response.status_code == 200
    assert response.json() == {"received": 2, "stored": 0, "rejected": 2}
    assert rows(telemetry_store) == []


def test_an_empty_batch_is_a_valid_envelope_with_nothing_to_store(anon_client, statements):
    assert anon_client.post("/telemetry/events", json={"events": []}).json() == {"received": 0, "stored": 0, "rejected": 0}
    assert inserts(statements) == []


@pytest.mark.parametrize(
    "bad",
    [
        {"eventId": "not-a-uuid"},
        {"timestamp": "2026-10-27 09:15:02"},
        {"event_type": "PageViewed"},
        {"schemaVersion": "1"},
        {"source": "mobile_app"},
        {"environment": "staging"},
        {"extra_top_level_key": "x"},
    ],
)
def test_an_event_that_breaks_the_envelope_is_rejected_alone(anon_client, telemetry_store, bad):
    good = event()

    response = anon_client.post("/telemetry/events", json={"events": [event(**bad), good]})

    assert response.json() == {"received": 2, "stored": 1, "rejected": 1}
    assert stored_ids(telemetry_store) == {good["eventId"]}


@pytest.mark.parametrize(
    "field", ["eventId", "timestamp", "sessionId", "userId", "event_type", "schemaVersion", "requestId", "source", "environment", "properties"]
)
def test_every_envelope_field_is_required(anon_client, field):
    incomplete = event()
    del incomplete[field]

    assert anon_client.post("/telemetry/events", json={"events": [incomplete]}).json() == {"received": 1, "stored": 0, "rejected": 1}


def test_an_event_outside_its_allowlist_is_rejected_and_logged_without_its_value(anon_client, telemetry_store, telemetry_log):
    leaky = event(properties={"page_route": "/inventory/products", "section": "inventory", "previous_route": None, "email": "ana@trackflow.com"})

    response = anon_client.post("/telemetry/events", json={"events": [leaky]})

    assert response.json() == {"received": 1, "stored": 0, "rejected": 1}
    assert "telemetry_schema_violation index=0 event_type=page_viewed" in telemetry_log.text
    assert "ana@trackflow.com" not in telemetry_log.text
    assert rows(telemetry_store) == []


def test_a_rejected_envelope_is_logged_by_field_never_by_value(anon_client, telemetry_log):
    anon_client.post("/telemetry/events", json={"events": [event(), event(userId="ana@trackflow.com")]})

    assert "telemetry_event_rejected index=1 reason=envelope fields=userId" in telemetry_log.text
    assert "ana@trackflow.com" not in telemetry_log.text
    assert "telemetry batch received=2 stored=1 rejected=1" in telemetry_log.text


def test_an_unknown_event_type_is_rejected(anon_client):
    response = anon_client.post("/telemetry/events", json={"events": [event("order_teleported")]})

    assert response.json() == {"received": 1, "stored": 0, "rejected": 1}


# =========================================================
# Bulk insert
# =========================================================


def test_the_whole_batch_is_one_insert_statement_not_one_per_event(anon_client, statements):
    response = anon_client.post("/telemetry/events", json={"events": [event() for _ in range(20)]})

    assert response.json()["stored"] == 20
    assert len(inserts(statements)) == 1
    sql, executemany = inserts(statements)[0]
    # Una sentencia INSERT … VALUES (…), (…), … con 7 parámetros por fila (created_at lo pone
    # la base), no un executemany ni un INSERT por evento.
    assert executemany is False
    assert sql.count("?") == 20 * 7


def test_a_retried_batch_does_not_duplicate_rows(anon_client, telemetry_store):
    batch = [event(), event()]

    first = anon_client.post("/telemetry/events", json={"events": batch}).json()
    retry = anon_client.post("/telemetry/events", json={"events": batch}).json()

    assert first == {"received": 2, "stored": 2, "rejected": 0}
    # El reintento llega bien (200) pero no hay filas nuevas: el id es el eventId.
    assert retry == {"received": 2, "stored": 0, "rejected": 0}
    assert len(rows(telemetry_store)) == 2


def test_the_same_event_twice_in_one_batch_is_one_row(anon_client, telemetry_store):
    twice = event()

    assert anon_client.post("/telemetry/events", json={"events": [twice, twice]}).json()["stored"] == 1
    assert len(rows(telemetry_store)) == 1


def test_the_stored_row_follows_the_storage_contract(anon_client, telemetry_store):
    sent = event("inbound_order_created", properties=INBOUND_PROPERTIES)

    anon_client.post("/telemetry/events", json={"events": [sent]})

    [row] = rows(telemetry_store)
    assert str(row.id) == sent["eventId"]
    assert row.event_type == "inbound_order_created"
    assert row.timestamp.isoformat(timespec="milliseconds").startswith("2026-10-27T09:15:02.481")
    assert (row.session_id, row.user_id, row.source) == (sent["sessionId"], sent["userId"], "backoffice_web")
    assert row.tags == {**INBOUND_PROPERTIES, "environment": "development", "schema_version": "1.0.0", "request_id": sent["requestId"]}
    assert row.created_at is not None


def test_a_storage_failure_answers_503_so_the_backoffice_retries(anon_client, monkeypatch, telemetry_log):
    def broken(events, session=None):
        raise OperationalError("INSERT", {}, Exception("connection refused"))

    monkeypatch.setattr(telemetry, "record_events", broken)

    response = anon_client.post("/telemetry/events", json={"events": [event()]})

    assert response.status_code == 503
    assert "telemetry_storage_failed error=OperationalError events=1" in telemetry_log.text


def test_events_emitted_by_the_api_are_stored_too(telemetry_store):
    telemetry.emit("direct_stock_edit_rejected", DIRECT_EDIT_PROPERTIES, user_id=str(uuid.uuid4()))

    [row] = rows(telemetry_store)
    assert (row.event_type, row.source, row.tags["environment"]) == ("direct_stock_edit_rejected", "api", config.TELEMETRY_ENVIRONMENT)
    assert row.tags["api_route"] == "/inventory/products/{sku_id}"


def test_a_storage_failure_never_breaks_the_business_operation_that_emits(monkeypatch):
    def unavailable():
        raise OperationalError("connect", {}, Exception("connection refused"))

    monkeypatch.setattr(telemetry, "open_session", unavailable)

    telemetry.emit("direct_stock_edit_rejected", DIRECT_EDIT_PROPERTIES, user_id=None)  # no lanza


# =========================================================
# Envelope laxo: se valida la lista, no cada evento
# =========================================================


def test_the_body_is_not_typed_as_a_list_of_telemetry_events():
    # Si FastAPI validara el cuerpo como list[TelemetryEvent], un evento inválido sería un 422 para todo el lote.
    parameters = inspect.signature(telemetry_router.receive_events).parameters

    assert list(parameters) == ["request"]
    assert telemetry.TelemetryEnvelope.model_fields["events"].annotation != list[telemetry.TelemetryEvent]


def test_it_needs_no_jwt_because_send_beacon_cannot_send_one(anon_client):
    assert anon_client.post("/telemetry/events", json={"events": [event()]}).status_code == 200


def test_a_send_beacon_body_sent_as_text_plain_is_accepted(anon_client):
    response = anon_client.post(
        "/telemetry/events", content=json.dumps({"events": [event()]}), headers={"Content-Type": "text/plain;charset=UTF-8"}
    )

    assert response.json() == {"received": 1, "stored": 1, "rejected": 0}


@pytest.mark.parametrize("body", [b"not json", b"[]", b'{"evnts": []}', b'{"events": "page_viewed"}', b'{"events": null}'])
def test_an_unreadable_envelope_is_the_only_case_rejected_as_a_whole(anon_client, body):
    response = anon_client.post("/telemetry/events", content=body, headers={"Content-Type": "text/plain"})

    assert response.status_code == 422
    assert all("input" not in item for item in response.json()["detail"])


def test_an_oversized_batch_is_rejected(anon_client, telemetry_store):
    response = anon_client.post("/telemetry/events", json={"events": [event() for _ in range(telemetry.MAX_BATCH_EVENTS + 1)]})

    assert response.status_code == 422
    assert rows(telemetry_store) == []


def test_an_oversized_body_is_rejected(anon_client):
    huge = {"events": [event(properties={"page_route": "x" * 300_000, "section": "inventory", "previous_route": None})]}

    assert anon_client.post("/telemetry/events", json=huge).status_code == 413


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
