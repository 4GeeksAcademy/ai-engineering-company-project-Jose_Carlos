"""POST /api/incidents — create_incident y validate_incident_fields."""

import pytest
from fastapi import BackgroundTasks

from packages.shared.incident_model import DESCRIPTION_MAX_LENGTH, TITLE_MAX_LENGTH
from services.api import incident_service, store
from services.api.errors import IncidentValidationError
from services.api.routes.incidents import create_incident

NOW = "2026-10-07T10:00:00+00:00"


def _create(payload):
    return create_incident(BackgroundTasks(), payload)


def _rejected(payload):
    with pytest.raises(IncidentValidationError) as error:
        _create(payload)
    assert store.get_all_incidents() == []
    return error


# =========================================================
# Camino feliz
# =========================================================


def test_create_incident_opens_it_with_server_side_id_and_timestamps(incident_payload, set_clock):
    set_clock(NOW)

    created = _create(incident_payload())

    assert set(created) == {
        "id", "title", "description", "category", "status", "origin", "branch", "created_at", "updated_at",
    }
    assert created["status"] == "open"
    assert created["created_at"] == created["updated_at"] == NOW
    assert {key: created[key] for key in incident_payload()} == incident_payload()
    assert store.get_incident_by_id(created["id"]) == created


def test_create_incident_queues_the_embedding_instead_of_computing_it_inline(incident_payload):
    background_tasks = BackgroundTasks()

    create_incident(background_tasks, incident_payload())

    assert [task.func for task in background_tasks.tasks] == [incident_service.index_pending]
    assert store.get_incident_embeddings() == []


# =========================================================
# Casos límite
# =========================================================


def test_create_trims_title_and_description(incident_payload):
    created = _create(incident_payload(title="  Palé dañado  ", description="\n Golpe en la descarga. \n"))

    assert created["title"] == "Palé dañado"
    assert created["description"] == "Golpe en la descarga."


def test_create_accepts_title_and_description_at_their_maximum_length(incident_payload):
    created = _create(incident_payload(title="t" * TITLE_MAX_LENGTH, description="d" * DESCRIPTION_MAX_LENGTH))

    assert len(created["title"]) == TITLE_MAX_LENGTH
    assert len(created["description"]) == DESCRIPTION_MAX_LENGTH


def test_length_limit_applies_after_trimming(incident_payload):
    created = _create(incident_payload(title=f"  {'t' * TITLE_MAX_LENGTH}  "))

    assert len(created["title"]) == TITLE_MAX_LENGTH


def test_create_ignores_id_and_timestamps_sent_by_client(incident_payload, set_clock):
    set_clock(NOW)

    created = _create(incident_payload(id=999, created_at="2000-01-01T00:00:00+00:00", updated_at="2000-01-01"))

    assert created["id"] != 999
    assert created["created_at"] == created["updated_at"] == NOW


@pytest.mark.parametrize("status", [None, ""])
def test_create_without_status_defaults_to_open(incident_payload, status):
    assert _create(incident_payload(status=status))["status"] == "open"


def test_create_accepts_an_explicit_allowed_status(incident_payload):
    assert _create(incident_payload(status="in_progress"))["status"] == "in_progress"


# =========================================================
# Modos de fallo
# =========================================================


@pytest.mark.parametrize("field", ["title", "description", "category", "origin", "branch"])
@pytest.mark.parametrize("how", ["missing", "none", "empty"])
def test_create_without_a_required_field_reports_it(incident_payload, error_codes, field, how):
    payload = incident_payload()
    if how == "missing":
        del payload[field]
    else:
        payload[field] = None if how == "none" else ""

    assert error_codes(_rejected(payload)) == {(field, "required")}


@pytest.mark.parametrize("field", ["title", "description"])
def test_create_with_whitespace_only_text_reports_it_as_required(incident_payload, error_codes, field):
    assert error_codes(_rejected(incident_payload(**{field: "   \n\t"}))) == {(field, "required")}


def test_create_rejects_texts_one_character_over_the_limit(incident_payload, error_codes):
    too_long = incident_payload(title="t" * (TITLE_MAX_LENGTH + 1), description="d" * (DESCRIPTION_MAX_LENGTH + 1))

    assert error_codes(_rejected(too_long)) == {("title", "too_long"), ("description", "too_long")}


@pytest.mark.parametrize("value", [123, True, ["Palé"], {"es": "Palé"}])
def test_create_rejects_non_text_title(incident_payload, error_codes, value):
    assert error_codes(_rejected(incident_payload(title=value))) == {("title", "invalid_type")}


@pytest.mark.parametrize("field", ["category", "origin", "branch", "status"])
@pytest.mark.parametrize("value", ["teleportation", "OPEN", 7, ["central"], {"value": "central"}])
def test_create_rejects_values_outside_the_allowed_list(incident_payload, error_codes, field, value):
    error = _rejected(incident_payload(**{field: value}))

    assert error_codes(error) == {(field, "invalid_value")}
    assert "Valores permitidos" in error.value.errors[0]["message"]


def test_create_reports_every_invalid_field_at_once(error_codes):
    error = _rejected({"title": "", "description": 5, "category": "nope", "branch": "moon"})

    assert error_codes(error) == {
        ("title", "required"),
        ("description", "invalid_type"),
        ("category", "invalid_value"),
        ("origin", "required"),
        ("branch", "invalid_value"),
    }


def test_rejected_incident_queues_no_background_work(incident_payload):
    background_tasks = BackgroundTasks()

    with pytest.raises(IncidentValidationError):
        create_incident(background_tasks, incident_payload(category="nope"))

    assert background_tasks.tasks == []
