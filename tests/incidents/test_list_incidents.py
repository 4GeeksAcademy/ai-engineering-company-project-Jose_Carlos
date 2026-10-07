"""GET /api/incidents — list_incidents y validate_filters."""

import pytest

from services.api.errors import IncidentValidationError
from services.api.routes.incidents import list_incidents


def _titles(incidents):
    return [incident["title"] for incident in incidents]


@pytest.fixture
def backlog(make_incident, set_clock):
    set_clock("2026-10-01T08:00:00+00:00")
    make_incident(title="Antigua", category="lost_parcel", origin="customer", branch="central")
    set_clock("2026-10-02T08:00:00+00:00")
    make_incident(title="Intermedia", category="lost_parcel", origin="branch", branch="la_office", status="resolved")
    set_clock("2026-10-03T08:00:00+00:00")
    make_incident(title="Reciente", category="system_failure", origin="customer", branch="central")


# =========================================================
# Camino feliz
# =========================================================


def test_list_returns_every_incident_newest_first(backlog):
    assert _titles(list_incidents()) == ["Reciente", "Intermedia", "Antigua"]


@pytest.mark.parametrize("filters,expected", [
    ({"status": "resolved"}, ["Intermedia"]),
    ({"origin": "customer"}, ["Reciente", "Antigua"]),
    ({"branch": "central"}, ["Reciente", "Antigua"]),
    ({"category": "lost_parcel"}, ["Intermedia", "Antigua"]),
])
def test_list_filters_by_each_field(backlog, filters, expected):
    assert _titles(list_incidents(**filters)) == expected


# =========================================================
# Casos límite
# =========================================================


def test_list_is_empty_when_there_are_no_incidents():
    assert list_incidents() == []
    assert list_incidents(status="open") == []


def test_list_combines_filters_with_and(backlog):
    assert _titles(list_incidents(category="lost_parcel", origin="customer")) == ["Antigua"]
    assert _titles(list_incidents(category="lost_parcel", origin="customer", branch="central", status="open")) == ["Antigua"]


def test_empty_filters_are_ignored(backlog):
    assert len(list_incidents(status="", origin="", branch="", category="")) == 3


def test_filter_without_matches_returns_an_empty_list(backlog):
    assert list_incidents(status="discarded") == []
    assert list_incidents(category="system_failure", status="resolved") == []


def test_incidents_created_at_the_same_instant_are_ordered_by_id(make_incident, set_clock):
    set_clock("2026-10-01T08:00:00+00:00")
    first, second = make_incident(title="Primera"), make_incident(title="Segunda")

    assert [incident["id"] for incident in list_incidents()] == [second["id"], first["id"]]


# =========================================================
# Modos de fallo
# =========================================================


@pytest.mark.parametrize("field", ["status", "origin", "branch", "category"])
def test_list_rejects_filter_value_outside_the_allowed_list(backlog, error_codes, field):
    with pytest.raises(IncidentValidationError) as error:
        list_incidents(**{field: "nope"})

    assert error_codes(error) == {(field, "invalid_value")}


def test_list_reports_every_invalid_filter(backlog, error_codes):
    with pytest.raises(IncidentValidationError) as error:
        list_incidents(status="OPEN", branch="moon", category="lost_parcel")

    assert error_codes(error) == {("status", "invalid_value"), ("branch", "invalid_value")}


def test_filter_values_are_case_sensitive(backlog):
    with pytest.raises(IncidentValidationError):
        list_incidents(category="Lost_Parcel")
