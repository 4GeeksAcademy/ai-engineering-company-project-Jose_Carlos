"""GET /api/incidents/search — search_incidents e incident_service.search."""

import pytest
from fastapi import HTTPException

from services.api import incident_service, store
from services.api.errors import IncidentValidationError
from services.api.routes.incidents import SEMANTIC_UNAVAILABLE, search_incidents

QUERY = "paquete perdido transportista"


def _search(q=QUERY, limit=20, **filters):
    return search_incidents(q=q, limit=limit, **filters)


# =========================================================
# Camino feliz
# =========================================================


def test_search_returns_the_related_incident_and_leaves_out_the_unrelated(make_incident, lost_parcel, system_failure):
    parcel = make_incident(**lost_parcel)
    make_incident(**system_failure)

    results = _search()

    assert [result["id"] for result in results] == [parcel["id"]]
    assert 0 < results[0]["score"] <= 1
    assert results[0]["possible_duplicate"] is False
    assert results[0]["title"] == parcel["title"]


def test_search_orders_results_from_most_to_least_similar(make_incident, lost_parcel):
    make_incident(**lost_parcel)
    make_incident(**{**lost_parcel, "description": "El transportista entregó el paquete en otra dirección."})
    make_incident(**{**lost_parcel, "title": "Paquete perdido", "description": "Paquete perdido por el transportista."})

    scores = [result["score"] for result in _search()]

    assert len(scores) >= 2
    assert scores == sorted(scores, reverse=True)


def test_search_indexes_pending_incidents_on_demand(make_incident, lost_parcel, system_failure):
    make_incident(**lost_parcel)
    make_incident(**system_failure)
    assert store.get_incident_embeddings() == []

    _search()

    assert len(store.get_incident_embeddings()) == 2


# =========================================================
# Casos límite
# =========================================================


def test_search_on_empty_database_returns_nothing():
    assert _search() == []


def test_search_limit_caps_the_number_of_results(make_incident, lost_parcel):
    for _ in range(3):
        make_incident(**lost_parcel)

    assert len(_search(limit=20)) == 3
    assert len(_search(limit=2)) == 2
    assert len(_search(limit=1)) == 1


def test_search_combines_with_the_listing_filters(make_incident, lost_parcel):
    make_incident(**lost_parcel)
    central = make_incident(**{**lost_parcel, "branch": "central", "status": "resolved"})

    assert [r["id"] for r in _search(branch="central")] == [central["id"]]
    assert [r["id"] for r in _search(branch="central", status="resolved")] == [central["id"]]
    assert _search(branch="central", status="open") == []
    assert len(_search(branch="", status="")) == 2


def test_search_trims_the_query(make_incident, lost_parcel):
    make_incident(**lost_parcel)

    assert _search(q=f"   {QUERY}   ") == _search()


def test_search_without_any_word_matches_nothing(make_incident, lost_parcel):
    make_incident(**lost_parcel)

    assert _search(q="!!! ???") == []


def test_search_ignores_accents_and_case(make_incident, lost_parcel):
    make_incident(**lost_parcel)

    assert _search(q="PAQUÉTE PERDÍDO TRANSPORTISTA") == _search()


@pytest.mark.parametrize("title,description,expected", [
    ("Palé dañado", "Golpe en la descarga.", "Palé dañado\nGolpe en la descarga."),
    # En el seed el título es el principio de la descripción: no se repite.
    ("Palé dañado", "Palé dañado en el muelle 3.", "Palé dañado en el muelle 3."),
    ("", "Solo descripción.", "Solo descripción."),
    (None, "Solo descripción.", "Solo descripción."),
    ("  Solo título  ", "", "Solo título\n"),
    ("", "", ""),
])
def test_incident_text_joins_title_and_description_without_repeating(title, description, expected):
    assert incident_service.incident_text(title, description) == expected


# =========================================================
# Modos de fallo
# =========================================================


@pytest.mark.parametrize("q", ["", "   ", "\n\t"])
def test_search_without_query_is_rejected(make_incident, error_codes, q):
    make_incident()

    with pytest.raises(IncidentValidationError) as error:
        _search(q=q)

    assert error_codes(error) == {("q", "required")}


def test_search_with_invalid_filter_is_rejected_before_searching(make_incident, error_codes, broken_embeddings):
    make_incident()

    with pytest.raises(IncidentValidationError) as error:
        _search(category="nope")

    assert error_codes(error) == {("category", "invalid_value")}


def test_search_reports_503_when_the_embeddings_provider_is_down(make_incident, broken_embeddings):
    make_incident()

    with pytest.raises(HTTPException) as error:
        _search()

    assert error.value.status_code == 503
    assert error.value.detail == SEMANTIC_UNAVAILABLE


def test_programming_error_in_search_is_not_disguised_as_503(make_incident, monkeypatch):
    make_incident()

    def boom(*args, **kwargs):
        raise KeyError("bug")

    monkeypatch.setattr(incident_service, "search", boom)

    with pytest.raises(KeyError):
        _search()
