"""GET /api/incidents/{id} — get_incident."""

import pytest
from fastapi import HTTPException

from services.api.routes.incidents import get_incident, update_incident_status


def _assert_not_found(incident_id):
    with pytest.raises(HTTPException) as error:
        get_incident(incident_id)
    assert error.value.status_code == 404
    assert error.value.detail == f"Incident {incident_id} not found"


# =========================================================
# Camino feliz
# =========================================================


def test_get_incident_returns_the_stored_incident(make_incident):
    created = make_incident()

    assert get_incident(created["id"]) == created


def test_get_incident_reflects_its_latest_status(make_incident):
    created = make_incident()
    update_incident_status(created["id"], {"status": "in_progress"})

    assert get_incident(created["id"])["status"] == "in_progress"


# =========================================================
# Casos límite
# =========================================================


@pytest.mark.parametrize("incident_id", [0, -1])
def test_get_incident_with_non_positive_id_is_not_found(make_incident, incident_id):
    make_incident()

    _assert_not_found(incident_id)


def test_get_incident_picks_the_right_one_among_several(make_incident):
    make_incident(title="Primera")
    second = make_incident(title="Segunda")

    assert get_incident(second["id"])["title"] == "Segunda"


# =========================================================
# Modos de fallo
# =========================================================


def test_get_unknown_incident_is_not_found(make_incident):
    created = make_incident()

    _assert_not_found(created["id"] + 1000)


def test_get_incident_on_empty_database_is_not_found():
    _assert_not_found(1)
