"""Tests de caracterización de services/api/main.py.

Congelan el comportamiento observable ACTUAL de la API (baseline previo a refactorizar),
no el comportamiento deseado. Si un test falla tras un cambio, es una posible regresión
o un cambio de contrato que debe revisarse conscientemente.
"""

from fastapi.testclient import TestClient

import services.api.main as main

HEADER = (
    "incident_id,date,country,customer_type,tracking_number,carrier,"
    "category,description,status,customer_email,satisfaction_score\n"
)

# 3 filas válidas y 2 inválidas que cubren las reglas de validación de scripts/analyze.py.
SAMPLE_CSV = HEADER + (
    "INC-1,2024-01-01,ES,B2C,TRK12345678,SEUR,LOST_PARCEL,Paquete perdido,CLOSED,a@b.com,4\n"
    "INC-2,2024-01-02,US,B2B,TRK87654321,UPS,DAMAGE,Caja rota en entrega,OPEN,c@d.com,\n"
    "INC-3,2024-01-03,ES,B2C,TRK11112222,MRW,LOST_PARCEL,Otro paquete perdido,CLOSED,e@f.com,5\n"
    "INC-4,2024-01-04,FR,B2C,123,UPS,FOO,abc,WEIRD,bad,9\n"
    ",2024-01-05,ES,B2C,TRK33334444,SEUR,DAMAGE,Golpe fuerte,CLOSED,g@h.com,\n"
)

SAMPLE_ANALYSIS = {
    "valid": 3,
    "invalid": 2,
    "categories": {"LOST_PARCEL": 2, "DAMAGE": 1},
    "statuses": {"CLOSED": 2, "OPEN": 1},
    "media_satisfaccion": 4.5,
    "errores": [
        {
            "incident_id": "INC-4",
            "errors": [
                "Invalid country",
                "Invalid tracking number",
                "Invalid category",
                "Invalid description",
                "Invalid status",
                "Invalid customer email",
                "Satisfaction score out of range",
            ],
        },
        {
            "incident_id": "",
            "errors": [
                "Missing required field: incident_id",
                "Closed incident without satisfaction score",
            ],
        },
    ],
}

NO_ANALYSIS = {"message": "No existe ningún análisis"}
EXPORT_URL = "/api/incidents/results/export"


def upload(client, content: bytes, field="file", filename="incidents.csv"):
    return client.post("/analyze", files={field: (filename, content, "text/csv")})


# =========================================================
# GET /
# =========================================================


def test_root_returns_welcome_message(client):
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {"message": "Bienvenid@ a la API de análisis de incidentes"}


def test_root_rejects_post(client):
    response = client.post("/")

    assert response.status_code == 405
    assert response.json() == {"detail": "Method Not Allowed"}


# =========================================================
# GET /openapi.json
# =========================================================


def test_openapi_exposes_current_routes_and_methods(client):
    response = client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert {path: sorted(ops) for path, ops in paths.items()} == {
        "/": ["get"],
        "/analyze": ["post"],
        "/api/incidents/results/export": ["get"],
        "/auth/login": ["post"],
        "/auth/me": ["get"],
        "/auth/token": ["post"],
        "/profiles/me": ["get", "put"],
        "/profiles/{user_id}": ["get", "put"],
        "/suppliers": ["get", "post"],
        "/suppliers/{supplier_id}": ["delete", "get"],
        "/suppliers/{supplier_id}/rate": ["patch"],
        "/suppliers/{supplier_id}/status": ["patch"],
        "/users": ["get", "post"],
        "/users/{user_id}": ["delete", "get", "put"],
    }


def test_openapi_analyze_requires_multipart_file_field(client):
    spec = client.get("/openapi.json").json()

    request_body = spec["paths"]["/analyze"]["post"]["requestBody"]
    assert request_body["required"] is True
    schema_ref = request_body["content"]["multipart/form-data"]["schema"]["$ref"]
    body_schema = spec["components"]["schemas"][schema_ref.rsplit("/", 1)[-1]]
    assert body_schema["required"] == ["file"]


def test_openapi_metadata_is_fastapi_default(client):
    info = client.get("/openapi.json").json()["info"]

    assert info == {"title": "FastAPI", "version": "0.1.0"}


# =========================================================
# GET /backoffice/
# =========================================================


def test_backoffice_serves_incident_analyzer_html(client):
    response = client.get("/backoffice/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "<title>Analizador de incidentes | TrackFlow</title>" in response.text
    assert 'id="analysisForm"' in response.text
    assert 'src="auth.js?v=1"' in response.text
    assert 'src="app.js?v=4"' in response.text


def test_backoffice_without_trailing_slash_redirects(client):
    response = client.get("/backoffice", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"].endswith("/backoffice/")


def test_backoffice_serves_its_static_script(client):
    response = client.get("/backoffice/app.js")

    assert response.status_code == 200
    assert "/api/incidents/results/export" in response.text


def test_backoffice_unknown_file_returns_404(client):
    response = client.get("/backoffice/does-not-exist.txt")

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


# =========================================================
# CORS (configuración por defecto, sin BACKOFFICE_CORS_ORIGINS)
# =========================================================


def test_cors_allows_default_backoffice_origin(client):
    response = client.options(
        "/analyze",
        headers={"Origin": "http://localhost:5500", "Access-Control-Request-Method": "POST"},
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5500"


def test_cors_allows_default_nextjs_origin(client):
    response = client.options(
        "/auth/me",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_cors_rejects_unknown_origin(client):
    response = client.options(
        "/analyze",
        headers={"Origin": "http://unknown.example", "Access-Control-Request-Method": "POST"},
    )

    assert response.status_code == 400
    assert response.text == "Disallowed CORS origin"


# =========================================================
# POST /analyze
# =========================================================


def test_analyze_returns_analysis_summary(client):
    response = upload(client, SAMPLE_CSV.encode("utf-8"))

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == SAMPLE_ANALYSIS


def test_analyze_stores_result_as_last_analysis(client):
    upload(client, SAMPLE_CSV.encode("utf-8"))

    assert main.last_analysis == SAMPLE_ANALYSIS


def test_analyze_empty_file_returns_zeroed_summary(client):
    response = upload(client, b"")

    assert response.status_code == 200
    assert response.json() == {
        "valid": 0,
        "invalid": 0,
        "categories": {},
        "statuses": {},
        "media_satisfaccion": 0,
        "errores": [],
    }


def test_analyze_leaves_uploaded_copy_in_temp_dir(client, isolated_api):
    # Comportamiento actual: el temporal se crea con delete=False y nunca se borra.
    upload(client, SAMPLE_CSV.encode("utf-8"))

    leftovers = list(isolated_api.iterdir())
    assert len(leftovers) == 1
    assert leftovers[0].suffix == ".csv"
    assert leftovers[0].read_text(encoding="utf-8") == SAMPLE_CSV


def test_analyze_without_file_returns_422(client):
    response = client.post("/analyze")

    assert response.status_code == 422
    assert response.json() == {
        "detail": [{"type": "missing", "loc": ["body", "file"], "msg": "Field required", "input": None}]
    }


def test_analyze_with_wrong_field_name_returns_422(client):
    response = upload(client, SAMPLE_CSV.encode("utf-8"), field="upload")

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "file"]


def test_analyze_non_utf8_file_returns_500_and_keeps_previous_state(auth_headers):
    client = TestClient(main.app, raise_server_exceptions=False, headers=auth_headers)

    response = upload(client, "incident_id\nñ\n".encode("latin-1"))

    assert response.status_code == 500
    assert response.text == "Internal Server Error"
    assert main.last_analysis is None


def test_analyze_rejects_get(client):
    response = client.get("/analyze")

    assert response.status_code == 405


# =========================================================
# GET /api/incidents/results/export
# =========================================================


def test_export_without_previous_analysis_returns_json_message(client):
    response = client.get(EXPORT_URL)

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == NO_ANALYSIS


def test_export_after_analyze_returns_csv_attachment(client):
    upload(client, SAMPLE_CSV.encode("utf-8"))

    response = client.get(EXPORT_URL)

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    assert response.headers["content-disposition"] == "attachment; filename=results.csv"
    assert response.text == (
        "metric,value\r\n"
        "valid_rows,3\r\n"
        "invalid_rows,2\r\n"
        "category_LOST_PARCEL,2\r\n"
        "category_DAMAGE,1\r\n"
        "status_CLOSED,2\r\n"
        "status_OPEN,1\r\n"
        "average_satisfaction,4.50\r\n"
    )


def test_export_after_empty_analysis_has_only_totals(client):
    upload(client, b"")

    response = client.get(EXPORT_URL)

    assert response.text == (
        "metric,value\r\n"
        "valid_rows,0\r\n"
        "invalid_rows,0\r\n"
        "average_satisfaction,0.00\r\n"
    )


def test_export_reflects_only_the_latest_analysis(client):
    upload(client, SAMPLE_CSV.encode("utf-8"))
    upload(client, b"")

    response = client.get(EXPORT_URL)

    assert "valid_rows,0\r\n" in response.text
    assert "category_" not in response.text


def test_export_uses_preloaded_state(client, monkeypatch):
    monkeypatch.setattr(
        main,
        "last_analysis",
        {
            "valid": 1,
            "invalid": 0,
            "categories": {"DAMAGE": 1},
            "statuses": {"CLOSED": 1},
            "media_satisfaccion": 10 / 3,
            "errores": [],
        },
    )

    response = client.get(EXPORT_URL)

    assert response.text == (
        "metric,value\r\n"
        "valid_rows,1\r\n"
        "invalid_rows,0\r\n"
        "category_DAMAGE,1\r\n"
        "status_CLOSED,1\r\n"
        "average_satisfaction,3.33\r\n"
    )
