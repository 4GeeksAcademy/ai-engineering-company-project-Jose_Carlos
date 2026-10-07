"""POST /api/incidents/suggest — suggest_for_draft e incident_service.suggest_category."""

import pytest
from fastapi import HTTPException

from services.api import incident_service
from services.api.errors import IncidentValidationError
from services.api.routes.incidents import SEMANTIC_UNAVAILABLE, suggest_for_draft

DRAFT = "No encuentran el paquete del cliente, el transportista lo ha perdido"


def _neighbour(category, score):
    return {"category": category, "score": score}


# =========================================================
# Camino feliz
# =========================================================


def test_suggest_returns_similar_incidents_and_their_category(make_incident, lost_parcel, system_failure):
    parcel = make_incident(**lost_parcel)
    make_incident(**system_failure)

    result = suggest_for_draft({"title": lost_parcel["title"], "description": lost_parcel["description"]})

    assert result["similar"][0]["id"] == parcel["id"]
    assert result["similar"][0]["possible_duplicate"] is True
    assert result["suggested_category"] == {"value": "lost_parcel", "confidence": 1.0}


def test_suggest_works_for_a_draft_worded_differently(make_incident, lost_parcel, system_failure):
    parcel = make_incident(**lost_parcel)
    make_incident(**system_failure)

    result = suggest_for_draft({"description": DRAFT})

    assert result["similar"][0]["id"] == parcel["id"]
    assert result["similar"][0]["possible_duplicate"] is False
    assert result["suggested_category"]["value"] == "lost_parcel"


def test_suggest_category_picks_the_category_with_most_weight():
    neighbours = [_neighbour("lost_parcel", 0.9), _neighbour("carrier_issue", 0.6)]

    assert incident_service.suggest_category(neighbours) == {"value": "lost_parcel", "confidence": 0.6}


# =========================================================
# Casos límite
# =========================================================


@pytest.mark.parametrize("draft", [
    {"title": "Paquete perdido en reparto"},
    {"description": DRAFT},
    {"title": "Paquete perdido en reparto", "description": ""},
    {"title": None, "description": DRAFT},
])
def test_suggest_needs_only_a_title_or_a_description(make_incident, lost_parcel, draft):
    parcel = make_incident(**lost_parcel)

    assert suggest_for_draft(draft)["similar"][0]["id"] == parcel["id"]


def test_suggest_without_history_suggests_nothing():
    assert suggest_for_draft({"description": DRAFT}) == {"similar": [], "suggested_category": None}


def test_suggest_with_unrelated_history_suggests_nothing(make_incident, system_failure):
    make_incident(**system_failure)

    assert suggest_for_draft({"title": "Paquete perdido"}) == {"similar": [], "suggested_category": None}


def test_suggest_category_rounds_confidence_to_two_decimals():
    neighbours = [_neighbour("lost_parcel", 0.5), _neighbour("lost_parcel", 0.5), _neighbour("other", 0.5)]

    assert incident_service.suggest_category(neighbours) == {"value": "lost_parcel", "confidence": 0.67}


def test_suggest_category_needs_a_dominant_category():
    # Tres categorías repartidas: ninguna llega a la mitad del peso.
    neighbours = [_neighbour("lost_parcel", 0.4), _neighbour("carrier_issue", 0.35), _neighbour("other", 0.35)]

    assert incident_service.suggest_category(neighbours) is None


def test_neighbours_below_the_triage_score_do_not_vote():
    triage_score = incident_service.get_embedder().triage_score
    weak, strong = triage_score - 0.01, triage_score + 0.2
    neighbours = [_neighbour("other", weak)] * 4 + [_neighbour("lost_parcel", strong)]

    assert incident_service.suggest_category(neighbours) == {"value": "lost_parcel", "confidence": 1.0}
    assert incident_service.suggest_category([_neighbour("other", weak)] * 5) is None


def test_only_the_closest_neighbours_vote():
    closest = [_neighbour("lost_parcel", 0.5)] * incident_service.TRIAGE_NEIGHBOURS
    crowd = [_neighbour("other", 0.9)] * 10

    assert incident_service.suggest_category(closest + crowd) == {"value": "lost_parcel", "confidence": 1.0}


def test_suggest_category_without_neighbours_is_none():
    assert incident_service.suggest_category([]) is None


# =========================================================
# Modos de fallo
# =========================================================


@pytest.mark.parametrize("draft", [
    {},
    {"title": "", "description": ""},
    {"title": "   ", "description": "\n"},
    {"title": 5, "description": ["Paquete perdido"]},
    {"title": None, "description": None},
])
def test_suggest_without_text_is_rejected(make_incident, error_codes, draft):
    make_incident()

    with pytest.raises(IncidentValidationError) as error:
        suggest_for_draft(draft)

    assert error_codes(error) == {("description", "required")}


def test_suggest_reports_503_when_the_embeddings_provider_is_down(make_incident, broken_embeddings):
    make_incident()

    with pytest.raises(HTTPException) as error:
        suggest_for_draft({"description": DRAFT})

    assert error.value.status_code == 503
    assert error.value.detail == SEMANTIC_UNAVAILABLE
