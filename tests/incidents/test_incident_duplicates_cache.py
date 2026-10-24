"""GET /api/incidents/duplicates con caché: HIT / MISS, caducidad e invalidación al crear una
incidencia o cambiar su estado."""

import pytest
from fastapi import HTTPException

from services.api import cache, embeddings, incident_service
from services.api.routes.incidents import INCIDENT_DUPLICATES_TTL_SECONDS, duplicate_groups, update_incident_status


@pytest.fixture
def clock(monkeypatch):
    class Clock:
        now = 1000.0

    monkeypatch.setattr(cache, "_clock", lambda: Clock.now)
    return Clock


@pytest.fixture
def computations(monkeypatch):
    """Cuántas veces se ha calculado de verdad la comparación O(n²) de embeddings."""
    calls = []
    original = incident_service.duplicate_groups
    monkeypatch.setattr(incident_service, "duplicate_groups", lambda: calls.append(1) or original())
    return calls


def test_second_read_is_served_from_the_cache(make_incident, lost_parcel, computations, clock):
    make_incident(**lost_parcel)
    make_incident(**lost_parcel)

    first = duplicate_groups()
    second = duplicate_groups()

    assert second == first
    assert first[0]["size"] == 2
    assert len(computations) == 1


def test_cached_groups_expire_after_the_ttl(computations, clock):
    duplicate_groups()

    clock.now += INCIDENT_DUPLICATES_TTL_SECONDS - 1
    duplicate_groups()
    assert len(computations) == 1

    clock.now += 1
    duplicate_groups()
    assert len(computations) == 2


def test_new_incident_invalidates_and_next_read_includes_it(make_incident, lost_parcel, clock):
    first = make_incident(**lost_parcel)
    assert duplicate_groups() == []  # queda cacheado: una sola incidencia no es un grupo

    second = make_incident(**lost_parcel)

    assert [group["incident_ids"] for group in duplicate_groups()] == [[first["id"], second["id"]]]


def test_status_change_invalidates_and_next_read_drops_the_closed_incident(make_incident, lost_parcel, clock):
    first = make_incident(**lost_parcel)
    make_incident(**lost_parcel)
    assert len(duplicate_groups()) == 1

    update_incident_status(first["id"], {"status": "in_progress"})
    update_incident_status(first["id"], {"status": "resolved"})

    assert duplicate_groups() == []  # la resuelta ya no está activa: el grupo desaparece


def test_unavailable_embeddings_are_not_cached(make_incident, lost_parcel, monkeypatch, clock):
    make_incident(**lost_parcel)
    make_incident(**lost_parcel)
    working_embed = incident_service.embed

    def unavailable(*args, **kwargs):
        raise embeddings.EmbeddingsUnavailable("proveedor caído")

    monkeypatch.setattr(incident_service, "embed", unavailable)
    with pytest.raises(HTTPException) as error:
        duplicate_groups()
    assert error.value.status_code == 503

    # El proveedor vuelve: la siguiente lectura calcula los grupos, no repite el 503.
    monkeypatch.setattr(incident_service, "embed", working_embed)
    assert len(duplicate_groups()) == 1
