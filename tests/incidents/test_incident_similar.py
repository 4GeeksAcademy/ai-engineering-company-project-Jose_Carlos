"""GET /api/incidents/{id}/similar — similar_incidents e incident_service.similar_to_incident."""

import pytest
from fastapi import HTTPException

from services.api.routes.incidents import SEMANTIC_UNAVAILABLE, similar_incidents


def _similar(incident_id, limit=5):
    return similar_incidents(incident_id, limit=limit)


# =========================================================
# Camino feliz
# =========================================================


def test_similar_returns_related_incidents_but_not_itself(make_incident, lost_parcel, system_failure):
    incident = make_incident(**lost_parcel)
    twin = make_incident(**lost_parcel)
    make_incident(**system_failure)

    results = _similar(incident["id"])

    assert [result["id"] for result in results] == [twin["id"]]
    assert results[0]["score"] == pytest.approx(1.0, abs=0.001)


def test_similar_flags_an_active_twin_as_possible_duplicate(make_incident, lost_parcel):
    incident = make_incident(**lost_parcel)
    make_incident(**{**lost_parcel, "status": "in_progress"})

    assert [result["possible_duplicate"] for result in _similar(incident["id"])] == [True]


# =========================================================
# Casos límite
# =========================================================


def test_similar_for_the_only_incident_returns_nothing(make_incident, lost_parcel):
    incident = make_incident(**lost_parcel)

    assert _similar(incident["id"]) == []


def test_similar_without_related_incidents_returns_nothing(make_incident, lost_parcel, system_failure):
    incident = make_incident(**lost_parcel)
    make_incident(**system_failure)

    assert _similar(incident["id"]) == []


@pytest.mark.parametrize("closed_status", ["resolved", "discarded"])
def test_closed_twin_is_similar_but_not_a_possible_duplicate(make_incident, lost_parcel, closed_status):
    # Un caso ya cerrado sirve de referencia, pero no es un duplicado que haya que fusionar.
    incident = make_incident(**lost_parcel)
    closed = make_incident(**{**lost_parcel, "status": closed_status})

    results = _similar(incident["id"])

    assert [(result["id"], result["possible_duplicate"]) for result in results] == [(closed["id"], False)]


def test_similar_limit_caps_the_number_of_results(make_incident, lost_parcel):
    incident = make_incident(**lost_parcel)
    for _ in range(3):
        make_incident(**lost_parcel)

    assert len(_similar(incident["id"], limit=5)) == 3
    assert len(_similar(incident["id"], limit=2)) == 2


# =========================================================
# Modos de fallo
# =========================================================


def test_similar_of_unknown_incident_is_not_found(make_incident):
    incident = make_incident()

    with pytest.raises(HTTPException) as error:
        _similar(incident["id"] + 1000)

    assert error.value.status_code == 404


def test_unknown_incident_is_reported_before_touching_embeddings(broken_embeddings):
    with pytest.raises(HTTPException) as error:
        _similar(1)

    assert error.value.status_code == 404


def test_similar_reports_503_when_the_embeddings_provider_is_down(make_incident, broken_embeddings):
    incident = make_incident()

    with pytest.raises(HTTPException) as error:
        _similar(incident["id"])

    assert error.value.status_code == 503
    assert error.value.detail == SEMANTIC_UNAVAILABLE
