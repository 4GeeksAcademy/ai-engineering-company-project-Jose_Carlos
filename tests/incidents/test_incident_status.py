"""PATCH /api/incidents/{id}/status — update_incident_status y validate_status_transition."""

import pytest
from fastapi import HTTPException

from packages.shared.incident_model import STATUS_TRANSITIONS, STATUSES, validate_status_transition
from services.api import store
from services.api.errors import IncidentValidationError
from services.api.routes.incidents import update_incident_status

CREATED_AT = "2026-10-01T08:00:00+00:00"
CHANGED_AT = "2026-10-07T10:00:00+00:00"

ALLOWED = [(current, new) for current, targets in STATUS_TRANSITIONS.items() for new in targets]
FORBIDDEN = [(current, new) for current in STATUSES for new in STATUSES if (current, new) not in ALLOWED]


@pytest.fixture
def incident_in(make_incident, set_clock):
    """Incidencia creada directamente en el estado pedido."""

    def _make(status):
        set_clock(CREATED_AT)
        incident = make_incident(status=status)
        set_clock(CHANGED_AT)
        return incident

    return _make


# =========================================================
# Camino feliz
# =========================================================


@pytest.mark.parametrize("current,new", ALLOWED)
def test_allowed_transition_updates_status_and_timestamp(incident_in, current, new):
    incident = incident_in(current)

    updated = update_incident_status(incident["id"], {"status": new})

    assert updated["status"] == new
    assert updated["updated_at"] == CHANGED_AT
    assert updated["created_at"] == CREATED_AT
    assert store.get_incident_by_id(incident["id"]) == updated


def test_full_lifecycle_from_open_to_resolved(incident_in):
    incident = incident_in("open")

    update_incident_status(incident["id"], {"status": "in_progress"})
    resolved = update_incident_status(incident["id"], {"status": "resolved"})

    assert resolved["status"] == "resolved"


def test_the_lifecycle_has_exactly_four_allowed_transitions():
    assert sorted(ALLOWED) == [
        ("in_progress", "discarded"),
        ("in_progress", "resolved"),
        ("open", "discarded"),
        ("open", "in_progress"),
    ]


# =========================================================
# Casos límite
# =========================================================


def test_status_change_leaves_every_other_field_untouched(incident_in):
    incident = incident_in("open")

    updated = update_incident_status(incident["id"], {"status": "in_progress"})

    untouched = set(incident) - {"status", "updated_at"}
    assert {key: updated[key] for key in untouched} == {key: incident[key] for key in untouched}


def test_extra_fields_in_the_body_are_ignored(incident_in):
    incident = incident_in("open")

    updated = update_incident_status(
        incident["id"], {"status": "in_progress", "title": "Otro título", "created_at": "2000-01-01"}
    )

    assert updated["title"] == incident["title"]
    assert updated["created_at"] == CREATED_AT


@pytest.mark.parametrize("status", ["open", "in_progress"])
def test_setting_the_current_status_again_is_rejected(incident_in, error_codes, status):
    incident = incident_in(status)

    with pytest.raises(IncidentValidationError) as error:
        update_incident_status(incident["id"], {"status": status})

    assert error_codes(error) == {("status", "invalid_transition")}


# =========================================================
# Modos de fallo
# =========================================================


@pytest.mark.parametrize("current,new", FORBIDDEN)
def test_forbidden_transition_is_rejected_and_keeps_the_incident(incident_in, error_codes, current, new):
    incident = incident_in(current)

    with pytest.raises(IncidentValidationError) as error:
        update_incident_status(incident["id"], {"status": new})

    assert error_codes(error) == {("status", "invalid_transition")}
    assert store.get_incident_by_id(incident["id"]) == incident


@pytest.mark.parametrize("final", ["resolved", "discarded"])
def test_final_status_message_explains_it_cannot_change(final):
    error = validate_status_transition(final, "open")

    assert "es un estado final" in error["message"]


def test_non_final_status_message_lists_where_it_can_go():
    error = validate_status_transition("open", "resolved")

    assert "solo se puede avanzar a: in_progress, discarded" in error["message"]


@pytest.mark.parametrize("payload,code", [
    ({}, "required"),
    ({"status": None}, "required"),
    ({"status": ""}, "required"),
    ({"status": "closed"}, "invalid_value"),
    ({"status": "IN_PROGRESS"}, "invalid_value"),
    ({"status": 1}, "invalid_value"),
    ({"status": ["in_progress"]}, "invalid_value"),
    ({"status": {"value": "in_progress"}}, "invalid_value"),
])
def test_malformed_status_is_rejected_and_keeps_the_incident(incident_in, error_codes, payload, code):
    incident = incident_in("open")

    with pytest.raises(IncidentValidationError) as error:
        update_incident_status(incident["id"], payload)

    assert error_codes(error) == {("status", code)}
    assert store.get_incident_by_id(incident["id"]) == incident


def test_status_change_of_unknown_incident_is_not_found(incident_in):
    incident = incident_in("open")

    with pytest.raises(HTTPException) as error:
        update_incident_status(incident["id"] + 1000, {"status": "in_progress"})

    assert error.value.status_code == 404
    assert store.get_all_incidents() == [incident]
