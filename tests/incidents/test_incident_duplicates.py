"""GET /api/incidents/duplicates — duplicate_groups."""

import pytest
from fastapi import HTTPException

from services.api.routes.incidents import SEMANTIC_UNAVAILABLE, duplicate_groups, update_incident_status


# =========================================================
# Camino feliz
# =========================================================


def test_duplicates_groups_active_incidents_describing_the_same_problem(
    make_incident, set_clock, lost_parcel, system_failure
):
    set_clock("2026-10-01T08:00:00+00:00")
    first = make_incident(**lost_parcel)
    set_clock("2026-10-02T08:00:00+00:00")
    second = make_incident(**{**lost_parcel, "origin": "branch", "branch": "central", "status": "in_progress"})
    make_incident(**system_failure)

    groups = duplicate_groups()

    assert groups == [
        {
            "size": 2,
            "title": lost_parcel["title"],
            "category": "lost_parcel",
            "branches": ["central", "zaragoza_office"],
            "origins": ["branch", "customer"],
            # La más antigua primero: es la que da título al grupo.
            "incident_ids": [first["id"], second["id"]],
        }
    ]


# =========================================================
# Casos límite
# =========================================================


def test_duplicates_on_empty_database_returns_nothing():
    assert duplicate_groups() == []


def test_single_incident_is_not_a_group(make_incident, lost_parcel):
    make_incident(**lost_parcel)

    assert duplicate_groups() == []


def test_unrelated_active_incidents_are_not_grouped(make_incident, lost_parcel, system_failure):
    make_incident(**lost_parcel)
    make_incident(**system_failure)

    assert duplicate_groups() == []


@pytest.mark.parametrize("closed_status", ["resolved", "discarded"])
def test_closed_incidents_do_not_count_as_duplicates(make_incident, lost_parcel, closed_status):
    make_incident(**lost_parcel)
    make_incident(**{**lost_parcel, "status": closed_status})

    assert duplicate_groups() == []


def test_group_disappears_when_a_duplicate_is_discarded(make_incident, lost_parcel):
    make_incident(**lost_parcel)
    duplicate = make_incident(**lost_parcel)
    assert len(duplicate_groups()) == 1

    update_incident_status(duplicate["id"], {"status": "discarded"})

    assert duplicate_groups() == []


def test_bigger_groups_come_first(make_incident, lost_parcel, system_failure):
    for _ in range(2):
        make_incident(**system_failure)
    for _ in range(3):
        make_incident(**lost_parcel)

    groups = duplicate_groups()

    assert [(group["size"], group["category"]) for group in groups] == [(3, "lost_parcel"), (2, "system_failure")]


def test_each_incident_belongs_to_a_single_group(make_incident, lost_parcel, system_failure):
    for _ in range(3):
        make_incident(**lost_parcel)
    for _ in range(2):
        make_incident(**system_failure)

    grouped_ids = [incident_id for group in duplicate_groups() for incident_id in group["incident_ids"]]

    assert len(grouped_ids) == len(set(grouped_ids)) == 5


# =========================================================
# Modos de fallo
# =========================================================


def test_duplicates_reports_503_when_the_embeddings_provider_is_down(make_incident, broken_embeddings):
    make_incident()

    with pytest.raises(HTTPException) as error:
        duplicate_groups()

    assert error.value.status_code == 503
    assert error.value.detail == SEMANTIC_UNAVAILABLE
