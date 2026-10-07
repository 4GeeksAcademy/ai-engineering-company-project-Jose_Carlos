"""GET /api/incidents/semantic-status — semantic_status, ensure_index e index_pending."""

from services.api import incident_service, store
from services.api.routes.incidents import get_incident, semantic_status

PROVIDER = "hashing-v1"


# =========================================================
# Camino feliz
# =========================================================


def test_status_reports_provider_indexed_and_pending(make_incident, lost_parcel, system_failure):
    make_incident(**lost_parcel)
    incident_service.ensure_index()
    make_incident(**system_failure)

    assert semantic_status() == {"provider": PROVIDER, "degraded": False, "indexed": 1, "pending": 1}


def test_ensure_index_computes_only_what_is_missing(make_incident, lost_parcel, system_failure):
    make_incident(**lost_parcel)
    make_incident(**system_failure)

    assert incident_service.ensure_index() == 2
    assert incident_service.ensure_index() == 0
    assert semantic_status()["pending"] == 0


def test_index_pending_stores_one_normalized_vector_per_incident(make_incident, lost_parcel):
    incident = make_incident(**lost_parcel)

    incident_service.index_pending()

    [record] = store.get_incident_embeddings()
    assert record["incident_id"] == incident["id"]
    assert record["model"] == PROVIDER
    assert abs(sum(value * value for value in record["vector"]) - 1.0) < 1e-3


# =========================================================
# Casos límite
# =========================================================


def test_status_on_empty_database_is_all_zero():
    assert semantic_status() == {"provider": PROVIDER, "degraded": False, "indexed": 0, "pending": 0}


def test_new_incident_is_pending_until_it_is_indexed(make_incident):
    make_incident()

    assert semantic_status()["pending"] == 1
    assert semantic_status()["indexed"] == 0


def test_embeddings_from_another_model_are_recomputed(make_incident, lost_parcel):
    incident = make_incident(**lost_parcel)
    incident_service.ensure_index()
    [record] = store.get_incident_embeddings()
    store.save_incident_embeddings([{**record, "model": "old-model"}])
    assert semantic_status()["pending"] == 1

    assert incident_service.ensure_index() == 1

    [record] = store.get_incident_embeddings()
    assert (record["incident_id"], record["model"]) == (incident["id"], PROVIDER)


def test_embedding_of_an_outdated_text_is_recomputed(make_incident, lost_parcel):
    make_incident(**lost_parcel)
    incident_service.ensure_index()
    [record] = store.get_incident_embeddings()
    store.save_incident_embeddings([{**record, "text_hash": "stale"}])

    assert semantic_status()["pending"] == 1
    assert incident_service.ensure_index() == 1


# =========================================================
# Modos de fallo
# =========================================================


def test_incident_survives_when_indexing_fails_and_stays_pending(make_incident, broken_embeddings):
    incident = make_incident()

    # No lanza: el alta ya se ha respondido y el indexado va en segundo plano.
    incident_service.index_pending()

    assert get_incident(incident["id"]) == incident
    assert store.get_incident_embeddings() == []
    assert semantic_status()["pending"] == 1


def test_pending_incident_is_indexed_once_the_provider_recovers(make_incident, monkeypatch):
    make_incident()
    real_embed = incident_service.embed

    def unavailable(*args, **kwargs):
        raise incident_service.EmbeddingsUnavailable("proveedor caído")

    monkeypatch.setattr(incident_service, "embed", unavailable)
    incident_service.index_pending()
    monkeypatch.setattr(incident_service, "embed", real_embed)

    incident_service.index_pending()

    assert semantic_status() == {"provider": PROVIDER, "degraded": False, "indexed": 1, "pending": 0}
