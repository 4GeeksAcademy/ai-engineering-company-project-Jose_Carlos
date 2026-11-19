"""Métrica de autenticación (hito 17, actividad adicional): la API emite `user_logged_in` al
emitir un token, y GET /telemetry/report la combina con `login_failed` del backoffice en
`auth_failure_rate`."""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlmodel import Session

from services.api import user_service
from services.api.user_models import UserRole
from services.telemetry_models import TelemetryEventRecord

PASSWORD = "s3cret-password"


def new_user(role=UserRole.USER) -> dict:
    user, _ = user_service.create_user(f"auth-rate-{uuid.uuid4().hex[:10]}@trackflow.com", PASSWORD, role=role)
    return user


def stored(engine, event_type: str) -> list[TelemetryEventRecord]:
    with Session(engine) as session:
        return list(session.exec(select(TelemetryEventRecord).where(TelemetryEventRecord.event_type == event_type)).scalars())


def login_failed_event(timestamp: str) -> dict:
    return {
        "eventId": str(uuid.uuid4()), "timestamp": timestamp, "sessionId": str(uuid.uuid4()), "userId": None,
        "event_type": "login_failed", "schemaVersion": "2.0.0", "requestId": str(uuid.uuid4()),
        "source": "backoffice_web", "environment": "test", "properties": {"failure_reason": "invalid_credentials"},
    }


def test_json_login_emits_user_logged_in_with_method_and_role(anon_client, telemetry_store):
    user = new_user(role=UserRole.MANAGER)

    response = anon_client.post("/auth/login", json={"email": user["email"], "password": PASSWORD})

    assert response.status_code == 200
    [row] = stored(telemetry_store, "user_logged_in")
    assert row.source == "api"
    assert row.user_id == user["id"]
    assert {"auth_method": row.tags["auth_method"], "user_role": row.tags["user_role"]} == {
        "auth_method": "password_json", "user_role": "manager",
    }


def test_swagger_login_is_oauth2_form(anon_client, telemetry_store):
    user = new_user()

    anon_client.post("/auth/token", data={"username": user["email"], "password": PASSWORD})

    [row] = stored(telemetry_store, "user_logged_in")
    assert row.tags["auth_method"] == "oauth2_form"


def test_wrong_password_emits_nothing_from_the_api(anon_client, telemetry_store):
    user = new_user()

    assert anon_client.post("/auth/login", json={"email": user["email"], "password": "wrong"}).status_code == 401
    assert stored(telemetry_store, "user_logged_in") == []


def test_report_combines_backoffice_failures_and_api_successes(anon_client, client):
    user = new_user()
    now = datetime.now(timezone.utc)
    iso = now.isoformat(timespec="milliseconds").replace("+00:00", "Z")

    # Dos fallos medidos por el backoffice y un éxito emitido por la API, hoy.
    receipt = anon_client.post("/telemetry/events", json={"events": [login_failed_event(iso), login_failed_event(iso)]})
    assert receipt.json()["stored"] == 2
    anon_client.post("/auth/login", json={"email": user["email"], "password": PASSWORD})

    body = client.get("/telemetry/report", params={
        "start_date": (now - timedelta(hours=1)).isoformat(), "end_date": (now + timedelta(hours=1)).isoformat(),
    }).json()

    assert body["metrics"]["auth_failure_rate"] == [
        {"date": now.date().isoformat(), "attempts": 3, "failed": 2, "succeeded": 1, "failure_rate": 0.6667},
    ]
