"""Gestor de incidencias (CONTEXT-8): modelo, endpoints, seed y capa semántica."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import services.api.main as main
from packages.shared.incident_model import BRANCHES, CATEGORIES, ORIGINS, STATUSES
from scripts.seed_incidents import seed_incidents
from services.api import incident_service, store

REPO = Path(__file__).resolve().parents[1]
DATASET = REPO / "csv" / "incidents-trackflow.csv"
BASE = "/api/incidents"

VALID = {
    "title": "Palé dañado en muelle 3",
    "description": "La carretilla golpeó un palé de mercancía durante la descarga.",
    "category": "warehouse_incident",
    "origin": "branch",
    "branch": "zaragoza_warehouse",
}


@pytest.fixture(autouse=True)
def empty_incidents():
    store.clear_incidents()
    yield
    store.clear_incidents()


def create(client, **overrides):
    response = client.post(BASE, json={**VALID, **overrides})
    assert response.status_code == 201, response.text
    return response.json()


def error_fields(response):
    return {error["field"] for error in response.json()["errors"]}


# =========================================================
# POST /api/incidents
# =========================================================


def test_create_incident_generates_id_and_timestamps(client):
    response = client.post(BASE, json={**VALID, "id": 999, "created_at": "2000-01-01T00:00:00+00:00"})

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {
        "id", "title", "description", "category", "status", "origin", "branch", "created_at", "updated_at",
    }
    assert body["id"] != 999
    assert body["status"] == "open"
    assert body["created_at"] == body["updated_at"]
    assert not body["created_at"].startswith("2000")


@pytest.mark.parametrize("field", ["title", "description", "category", "origin", "branch"])
def test_create_without_required_field_returns_400_with_field(client, field):
    payload = {key: value for key, value in VALID.items() if key != field}

    response = client.post(BASE, json=payload)

    assert response.status_code == 400
    assert response.json()["errors"] == [
        {"field": field, "code": "required", "message": f"El campo '{field}' es obligatorio."}
    ]
    assert store.get_all_incidents() == []


@pytest.mark.parametrize("field", ["category", "origin", "branch", "status"])
def test_create_with_value_not_allowed_returns_400_with_field(client, field):
    response = client.post(BASE, json={**VALID, field: "nope"})

    assert response.status_code == 400
    assert error_fields(response) == {field}
    assert response.json()["errors"][0]["code"] == "invalid_value"


def test_create_reports_every_invalid_field(client):
    response = client.post(BASE, json={"title": "   ", "origin": "customer", "branch": "madrid"})

    assert response.status_code == 400
    assert error_fields(response) == {"title", "description", "category", "branch"}


def test_create_with_malformed_body_returns_400(client):
    response = client.post(BASE, content="not json", headers={"Content-Type": "application/json"})

    assert response.status_code == 400
    assert "errors" in response.json()


def test_incident_routes_require_token(anon_client):
    assert anon_client.get(BASE).status_code == 401
    assert anon_client.post(BASE, json=VALID).status_code == 401
    assert anon_client.get(f"{BASE}/summary").status_code == 401


# =========================================================
# GET /api/incidents y /api/incidents/{id}
# =========================================================


def test_list_is_empty_when_there_are_no_incidents(client):
    response = client.get(BASE)

    assert response.status_code == 200
    assert response.json() == []


def test_list_filters_combine(client):
    create(client)
    create(client, origin="customer", branch="central", category="client_complaint")
    create(client, origin="customer", branch="la_office", category="lost_parcel")

    assert len(client.get(BASE).json()) == 3
    assert len(client.get(BASE, params={"origin": "customer"}).json()) == 2
    assert len(client.get(BASE, params={"origin": "customer", "branch": "central"}).json()) == 1
    assert len(client.get(BASE, params={"category": "lost_parcel"}).json()) == 1
    assert client.get(BASE, params={"status": "resolved"}).json() == []


def test_list_with_invalid_filter_returns_400_with_field(client):
    response = client.get(BASE, params={"branch": "madrid"})

    assert response.status_code == 400
    assert error_fields(response) == {"branch"}


def test_get_incident_detail_and_404(client):
    created = create(client)

    assert client.get(f"{BASE}/{created['id']}").json() == created

    missing = client.get(f"{BASE}/999999")
    assert missing.status_code == 404
    assert missing.json() == {"detail": "Incident 999999 not found"}


# =========================================================
# PATCH /api/incidents/{id}/status
# =========================================================


@pytest.mark.parametrize(
    "path",
    [
        ["in_progress", "resolved"],
        ["in_progress", "discarded"],
        ["discarded"],
    ],
)
def test_valid_status_transitions(client, path):
    incident = create(client)

    for new_status in path:
        response = client.patch(f"{BASE}/{incident['id']}/status", json={"status": new_status})
        assert response.status_code == 200
        assert response.json()["status"] == new_status

    assert response.json()["updated_at"] > incident["updated_at"]
    assert response.json()["created_at"] == incident["created_at"]


@pytest.mark.parametrize(
    "path, rejected",
    [
        ([], "resolved"),
        ([], "open"),
        (["in_progress"], "open"),
        (["in_progress", "resolved"], "in_progress"),
        (["discarded"], "open"),
    ],
)
def test_invalid_status_transitions_return_400(client, path, rejected):
    incident = create(client)
    for new_status in path:
        client.patch(f"{BASE}/{incident['id']}/status", json={"status": new_status})
    before = client.get(f"{BASE}/{incident['id']}").json()

    response = client.patch(f"{BASE}/{incident['id']}/status", json={"status": rejected})

    assert response.status_code == 400
    assert response.json()["errors"][0]["field"] == "status"
    assert response.json()["errors"][0]["code"] == "invalid_transition"
    assert client.get(f"{BASE}/{incident['id']}").json() == before


def test_status_update_validates_value_and_existence(client):
    incident = create(client)

    assert client.patch(f"{BASE}/{incident['id']}/status", json={"status": "closed"}).status_code == 400
    assert client.patch(f"{BASE}/{incident['id']}/status", json={}).status_code == 400
    assert client.patch(f"{BASE}/999999/status", json={"status": "in_progress"}).status_code == 404


# =========================================================
# GET /api/incidents/summary
# =========================================================


def test_summary_is_zeroed_when_there_are_no_incidents(client):
    response = client.get(f"{BASE}/summary")

    assert response.status_code == 200
    assert response.json() == {
        "total": 0,
        "by_status": dict.fromkeys(STATUSES, 0),
        "by_category": dict.fromkeys(CATEGORIES, 0),
        "by_origin": dict.fromkeys(ORIGINS, 0),
        "by_branch": dict.fromkeys(BRANCHES, 0),
    }


def test_summary_counts_by_status_category_origin_and_branch(client):
    first = create(client)
    create(client, origin="customer", branch="central", category="client_complaint")
    client.patch(f"{BASE}/{first['id']}/status", json={"status": "in_progress"})

    summary = client.get(f"{BASE}/summary").json()

    assert summary["total"] == 2
    assert summary["by_status"] == {"open": 1, "in_progress": 1, "resolved": 0, "discarded": 0}
    assert summary["by_category"]["warehouse_incident"] == 1
    assert summary["by_category"]["client_complaint"] == 1
    assert summary["by_origin"] == {"customer": 1, "branch": 1, "internal": 0}
    assert summary["by_branch"]["zaragoza_warehouse"] == 1
    assert summary["by_branch"]["central"] == 1


# =========================================================
# Errores no controlados
# =========================================================


def test_unhandled_error_returns_generic_500_without_stack_trace(auth_headers, monkeypatch):
    def boom():
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr(store, "get_all_incidents", boom)
    client = TestClient(main.app, raise_server_exceptions=False, headers=auth_headers)

    response = client.get(BASE)

    assert response.status_code == 500
    assert response.json() == {"detail": "Se ha producido un error interno. Inténtalo de nuevo más tarde."}
    assert "secret" not in response.text
    assert "Traceback" not in response.text


# =========================================================
# Seed desde el CSV del analizador
# =========================================================


def test_seed_loads_valid_rows_with_context_totals(client):
    result = seed_incidents(DATASET)

    assert result["inserted"] == 95
    assert result["skipped"] == 0
    assert len(result["invalid"]) == 5
    assert all(record["errors"] for record in result["invalid"])

    summary = client.get(f"{BASE}/summary").json()
    assert summary["total"] == 95
    # Valores esperados tras el seed (CONTEXT-8)
    assert summary["by_status"] == {"open": 29, "in_progress": 0, "resolved": 52, "discarded": 14}
    assert {k: v for k, v in summary["by_category"].items() if v} == {
        "lost_parcel": 14,
        "carrier_issue": 45,
        "delivery_failure": 19,
        "returns_issue": 17,
    }
    assert summary["by_origin"] == {"customer": 95, "branch": 0, "internal": 0}
    assert {k for k, v in summary["by_branch"].items() if v} == {"la_office", "zaragoza_office"}


def test_seed_applies_csv_to_model_transformations(client):
    seed_incidents(DATASET)

    incidents = client.get(BASE).json()

    for incident in incidents:
        assert incident["origin"] == "customer"
        assert incident["title"] == incident["description"].strip()[:120].strip()
        assert incident["created_at"].endswith("T00:00:00+00:00")
        assert incident["updated_at"] == incident["created_at"]
        assert "incident_id" not in incident


def test_seed_is_idempotent(client):
    seed_incidents(DATASET)

    second = seed_incidents(DATASET)

    assert second["inserted"] == 0
    assert second["skipped"] == 95
    assert client.get(f"{BASE}/summary").json()["total"] == 95


def test_seed_without_incident_id_falls_back_to_title_and_date(tmp_path):
    # Sin incident_id la fila no pasa la validación del analizador: no se inserta.
    csv_file = tmp_path / "one.csv"
    csv_file.write_text(
        "incident_id,date,country,customer_type,tracking_number,carrier,category,description,status,"
        "customer_email,satisfaction_score\n"
        ",2024-01-05,ES,B2C,TRK33334444,SEUR,DAMAGE,Golpe fuerte en la caja,OPEN,g@h.com,\n"
        "X-1,2024-13-45,ES,B2C,TRK33334444,SEUR,DAMAGE,Golpe fuerte en la caja,OPEN,g@h.com,\n",
        encoding="utf-8",
    )

    result = seed_incidents(csv_file)

    assert result["inserted"] == 0
    assert [record["incident_id"] for record in result["invalid"]] == ["UNKNOWN", "X-1"]
    assert "Invalid date" in result["invalid"][1]["errors"][0]


# =========================================================
# Capa semántica (embeddings)
# =========================================================


def test_search_returns_closest_incident_first(client):
    create(client)
    parcel = create(
        client,
        title="Paquete extraviado en tránsito",
        description="El cliente no ha recibido el paquete y el carrier lo marca como entregado.",
        category="lost_parcel",
        origin="customer",
        branch="central",
    )

    response = client.get(f"{BASE}/search", params={"q": "paquete no recibido por el cliente"})

    assert response.status_code == 200
    results = response.json()
    assert results[0]["id"] == parcel["id"]
    assert 0 < results[0]["score"] <= 1

    filtered = client.get(f"{BASE}/search", params={"q": "paquete no recibido", "branch": "la_office"})
    assert filtered.json() == []


def test_search_requires_query_and_works_on_empty_database(client):
    assert client.get(f"{BASE}/search").status_code == 400
    assert client.get(f"{BASE}/search", params={"q": "paquete"}).json() == []
    assert client.get(f"{BASE}/duplicates").json() == []


def test_suggest_returns_similar_incidents_duplicates_and_category(client):
    seed_incidents(DATASET)
    open_incident = next(i for i in client.get(BASE).json() if i["status"] == "open")

    response = client.post(f"{BASE}/suggest", json={"description": open_incident["description"]})

    assert response.status_code == 200
    body = response.json()
    assert body["similar"][0]["score"] > 0.99
    assert any(item["possible_duplicate"] for item in body["similar"])
    assert body["suggested_category"]["value"] == open_incident["category"]

    assert client.post(f"{BASE}/suggest", json={"title": " "}).status_code == 400


def test_similar_incidents_excludes_itself(client):
    first = create(client)
    twin = create(client)
    create(client, title="Fallo del WMS", description="La integración con el carrier devuelve error 500.",
           category="system_failure", origin="internal", branch="central")

    similar = client.get(f"{BASE}/{first['id']}/similar").json()

    assert [item["id"] for item in similar] == [twin["id"]]
    assert client.get(f"{BASE}/999999/similar").status_code == 404


def test_duplicate_groups_only_cluster_active_incidents(client):
    first = create(client)
    second = create(client, branch="la_warehouse")
    closed = create(client)
    client.patch(f"{BASE}/{closed['id']}/status", json={"status": "discarded"})
    create(client, title="Fallo del WMS", description="La integración con el carrier devuelve error 500.",
           category="system_failure", origin="internal", branch="central")

    groups = client.get(f"{BASE}/duplicates").json()

    assert len(groups) == 1
    assert groups[0]["size"] == 2
    assert groups[0]["incident_ids"] == [first["id"], second["id"]]
    assert groups[0]["branches"] == ["la_warehouse", "zaragoza_warehouse"]


def test_incident_is_created_even_if_embeddings_fail(client, monkeypatch):
    def boom():
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(incident_service, "ensure_index", boom)

    assert client.post(BASE, json=VALID).status_code == 201
    assert client.get(f"{BASE}/search", params={"q": "palé"}).status_code == 503
