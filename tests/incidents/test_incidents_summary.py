"""GET /api/incidents/summary — incidents_summary."""

import pytest
from fastapi import BackgroundTasks

from packages.shared.incident_model import BRANCHES, CATEGORIES, ORIGINS, STATUSES
from services.api.errors import IncidentValidationError
from services.api.routes.incidents import create_incident, incidents_summary, update_incident_status


def _non_zero(counts):
    return {key: value for key, value in counts.items() if value}


# =========================================================
# Camino feliz
# =========================================================


def test_summary_counts_by_status_category_origin_and_branch(make_incident):
    make_incident(category="lost_parcel", origin="customer", branch="central")
    make_incident(category="lost_parcel", origin="branch", branch="la_office", status="resolved")
    make_incident(category="system_failure", origin="customer", branch="central")

    summary = incidents_summary()

    assert summary["total"] == 3
    assert _non_zero(summary["by_status"]) == {"open": 2, "resolved": 1}
    assert _non_zero(summary["by_category"]) == {"lost_parcel": 2, "system_failure": 1}
    assert _non_zero(summary["by_origin"]) == {"customer": 2, "branch": 1}
    assert _non_zero(summary["by_branch"]) == {"central": 2, "la_office": 1}


# =========================================================
# Casos límite
# =========================================================


def test_summary_without_incidents_lists_every_possible_value_at_zero():
    summary = incidents_summary()

    assert summary == {
        "total": 0,
        "by_status": dict.fromkeys(STATUSES, 0),
        "by_category": dict.fromkeys(CATEGORIES, 0),
        "by_origin": dict.fromkeys(ORIGINS, 0),
        "by_branch": dict.fromkeys(BRANCHES, 0),
    }


def test_every_breakdown_adds_up_to_the_total(make_incident):
    for category in CATEGORIES:
        make_incident(category=category)

    summary = incidents_summary()

    assert summary["total"] == len(CATEGORIES)
    for breakdown in ("by_status", "by_category", "by_origin", "by_branch"):
        assert sum(summary[breakdown].values()) == summary["total"]
    assert set(summary["by_category"].values()) == {1}


# =========================================================
# Modos de fallo
# =========================================================


def test_status_change_moves_the_incident_between_counters(make_incident):
    incident = make_incident()

    update_incident_status(incident["id"], {"status": "in_progress"})

    summary = incidents_summary()
    assert summary["total"] == 1
    assert _non_zero(summary["by_status"]) == {"in_progress": 1}


def test_rejected_incident_is_not_counted(make_incident, incident_payload):
    make_incident()
    with pytest.raises(IncidentValidationError):
        create_incident(BackgroundTasks(), incident_payload(branch="moon"))

    assert incidents_summary()["total"] == 1
