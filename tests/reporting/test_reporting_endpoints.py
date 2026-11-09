"""Endpoints de services/reporting/ (hito 19, Fase 5)."""

import ast
import uuid
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

import services.api.main as main
from data.pipelines.weekly_warehouse_client_performance import config, connections, queries, run_log, trigger
from services.api import user_service
from services.api.security import create_access_token
from services.api.user_models import UserRole
from services.reporting import router as reporting_router
from tests.reporting.conftest import AS_OF, PREVIOUS_WEEK, WEEK

KPI_URL = "/reporting/weekly-warehouse-client-performance"
LATEST_URL = "/reporting/pipeline-runs/latest"
RUNS_URL = "/reporting/pipeline-runs"
REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def admin_headers():
    user, _ = user_service.create_user(f"reporting-admin-{uuid.uuid4().hex[:8]}@trackflow.com", "admin-password",
                                       role=UserRole.ADMIN)
    return {"Authorization": f"Bearer {create_access_token(user['id'])}"}


@pytest.fixture
def admin_client(admin_headers):
    return TestClient(main.app, headers=admin_headers)


@pytest.fixture
def loaded(week_of_activity):
    """La semana de la fixture ya cargada por el pipeline (sin Prefect: funciones puras)."""
    from data.pipelines.weekly_warehouse_client_performance import extract, load, transform

    events = extract.extract_inventory_events(week_of_activity, [WEEK], AS_OF, "test")
    weekly = transform.transform_weekly_performance(events, [WEEK]).weekly
    run_id = uuid.uuid4()
    run_log.start_run(week_of_activity, run_id=run_id, pipeline_name=config.PIPELINE_NAME, trigger="scheduled",
                      triggered_by=None, started_at=AS_OF, source_watermark=AS_OF, parameters={"lookback_weeks": 0},
                      code_version="abc1234")
    result = load.load_weekly_performance(week_of_activity, weekly, [WEEK], AS_OF)
    run_log.finish_run(week_of_activity, run_id, finished_at=AS_OF + timedelta(seconds=41),
                       weeks_processed=[WEEK.isoformat()],
                       counters={"events_extracted": len(events), **result._asdict()}, warnings=[])
    return run_id


# =========================================================
# GET /reporting/weekly-warehouse-client-performance
# =========================================================


def test_kpi_feed_matches_the_briefing_contract(client, loaded):
    response = client.get(KPI_URL)
    assert response.status_code == 200
    body = response.json()
    assert body["week_start"] == WEEK.isoformat()
    assert body["computed_at"] == "2026-11-09T06:00:00Z"
    assert [(e["warehouse"], e["client_id"]) for e in body["entries"]] == [
        ("los_angeles", "glowlab_cosmetics"), ("los_angeles", "purestep_footwear"), ("zaragoza", "purestep_footwear"),
    ]
    assert body["entries"][1] == {
        "warehouse": "los_angeles",
        "client_id": "purestep_footwear",
        "inbound_units_count": 420,
        "outbound_orders_count": 4,
        "stockout_events_count": 1,
        "discrepancy_events_count": 1,
        "discrepancy_rate": 0.25,
    }


def test_kpi_feed_accepts_an_explicit_week(client, loaded):
    assert client.get(KPI_URL, params={"week_start": WEEK.isoformat()}).status_code == 200
    assert client.get(KPI_URL, params={"week_start": PREVIOUS_WEEK.isoformat()}).status_code == 404


@pytest.mark.parametrize("value", ["2026-11-03", "02/11/2026"])
def test_kpi_feed_rejects_a_week_that_is_not_a_monday(client, reporting_db, value):
    assert client.get(KPI_URL, params={"week_start": value}).status_code == 422


def test_kpi_feed_is_404_before_the_first_run(client, monkeypatch):
    from sqlalchemy import create_engine

    monkeypatch.setattr(connections, "api_engine", lambda: create_engine("sqlite://"))  # sin esquema reporting
    response = client.get(KPI_URL)
    assert response.status_code == 404
    assert response.json() == {"detail": "Todavía no hay ninguna semana calculada"}


def test_kpi_feed_requires_a_session(anon_client, loaded):
    assert anon_client.get(KPI_URL).status_code == 401


def test_kpi_feed_is_503_when_the_database_fails(client, monkeypatch):
    def down(*args, **kwargs):
        raise OperationalError("SELECT", {}, Exception("down"))

    monkeypatch.setattr(queries, "get_weekly_performance", down)
    assert client.get(KPI_URL).status_code == 503


# =========================================================
# GET /reporting/pipeline-runs/latest
# =========================================================


def test_latest_run_returns_status_times_and_processed_records(client, loaded):
    response = client.get(LATEST_URL)
    assert response.status_code == 200
    body = response.json()
    assert body["pipeline_name"] == config.PIPELINE_NAME
    assert body["latest_successful_run_id"] == str(loaded)
    run = body["latest_run"]
    assert run["run_id"] == str(loaded)
    assert run["status"] == "completed"
    assert (run["started_at"], run["finished_at"]) == ("2026-11-09T06:00:00Z", "2026-11-09T06:00:41Z")
    assert (run["events_extracted"], run["rows_upserted"], run["rows_deleted"]) == (13, 3, 0)
    assert run["weeks_processed"] == [WEEK.isoformat()]
    assert run["error_stage"] is None and run["error_message"] is None


def test_latest_run_is_404_when_the_pipeline_never_ran(client, reporting_db):
    assert client.get(LATEST_URL).status_code == 404


def test_latest_run_requires_a_session(anon_client, loaded):
    assert anon_client.get(LATEST_URL).status_code == 401


# =========================================================
# POST /reporting/pipeline-runs
# =========================================================


def test_manual_run_calls_the_flow_from_data_pipelines(admin_client, reporting_db, monkeypatch):
    calls = []
    monkeypatch.setattr(trigger, "run_locally", lambda parameters: calls.append(parameters))

    response = admin_client.post(RUNS_URL, json={"week_start": WEEK.isoformat(), "lookback_weeks": 0})
    assert response.status_code == 202
    assert response.json() == {"pipeline_name": config.PIPELINE_NAME, "status": "scheduled", "mode": "local",
                               "flow_run_id": None}
    # La BackgroundTask ya se ejecutó al terminar la respuesta: con los parámetros de la corrida manual.
    assert calls == [{"week_start": WEEK, "lookback_weeks": 0, "trigger": "manual", "triggered_by": calls[0]["triggered_by"]}]
    assert calls[0]["triggered_by"]


def test_manual_run_without_body_uses_the_defaults(admin_client, reporting_db, monkeypatch):
    calls = []
    monkeypatch.setattr(trigger, "run_locally", lambda parameters: calls.append(parameters))
    assert admin_client.post(RUNS_URL).status_code == 202
    assert (calls[0]["week_start"], calls[0]["lookback_weeks"]) == (None, config.DEFAULT_LOOKBACK_WEEKS)


def test_manual_run_in_deployment_mode_schedules_the_prefect_deployment(admin_client, reporting_db, monkeypatch):
    import prefect.deployments

    scheduled = {}

    class FlowRun:
        id = uuid.UUID("0d8f6c1e-2c55-4a9e-8a7b-6a2b9f4e1c33")

    def fake_run_deployment(name, parameters, timeout):
        scheduled.update(name=name, parameters=parameters, timeout=timeout)
        return FlowRun()

    monkeypatch.setenv(trigger.MODE_ENV, "deployment")
    monkeypatch.setattr(prefect.deployments, "run_deployment", fake_run_deployment)
    response = admin_client.post(RUNS_URL, json={})
    assert response.status_code == 202
    assert response.json()["flow_run_id"] == str(FlowRun.id)
    assert scheduled["name"] == config.DEPLOYMENT_NAME and scheduled["timeout"] == 0
    assert scheduled["parameters"]["trigger"] == "manual"


def test_manual_run_is_503_when_prefect_is_unreachable(admin_client, reporting_db, monkeypatch):
    import prefect.deployments

    def unreachable(*args, **kwargs):
        raise ConnectionError("prefect down")

    monkeypatch.setenv(trigger.MODE_ENV, "deployment")
    monkeypatch.setattr(prefect.deployments, "run_deployment", unreachable)
    assert admin_client.post(RUNS_URL, json={}).status_code == 503


def test_manual_run_is_409_while_another_run_is_in_progress(admin_client, reporting_db, monkeypatch):
    monkeypatch.setattr(trigger, "run_locally", lambda parameters: pytest.fail("no debe programarse"))
    run_log.start_run(reporting_db, run_id=uuid.uuid4(), pipeline_name=config.PIPELINE_NAME, trigger="scheduled",
                      triggered_by=None, started_at=config.utc_now(), source_watermark=AS_OF, parameters={},
                      code_version=None)
    assert admin_client.post(RUNS_URL, json={}).status_code == 409


@pytest.mark.parametrize("body", [
    {"week_start": "2026-11-03"},          # no es lunes
    {"week_start": "2099-01-05"},          # semana futura
    {"lookback_weeks": 13},                # fuera de rango
])
def test_manual_run_validates_its_parameters(admin_client, reporting_db, monkeypatch, body):
    monkeypatch.setattr(trigger, "run_locally", lambda parameters: pytest.fail("no debe programarse"))
    assert admin_client.post(RUNS_URL, json=body).status_code == 422


def test_manual_run_requires_admin(client, anon_client, reporting_db):
    assert anon_client.post(RUNS_URL, json={}).status_code == 401
    assert client.post(RUNS_URL, json={}).status_code == 403


# =========================================================
# Separación de módulos
# =========================================================


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
            names |= {f"{node.module}.{alias.name}" for alias in node.names}
    return names


def test_services_reporting_holds_no_etl_logic():
    imports = set().union(*(_imports(path) for path in (REPO / "services" / "reporting").glob("*.py")))
    assert not any(name.split(".")[0] in {"pandas", "prefect"} for name in imports)
    forbidden = {"extract", "transform", "load", "quality"}
    pipeline_modules = {name.rsplit(".", 1)[-1] for name in imports
                        if name.startswith("data.pipelines.weekly_warehouse_client_performance.")}
    assert not pipeline_modules & forbidden
    assert {"queries", "run_log", "trigger"} <= pipeline_modules


def test_reporting_is_a_separate_module_from_telemetry():
    assert reporting_router.prefix == "/reporting"
    paths = set(main.app.openapi()["paths"])
    assert {KPI_URL, LATEST_URL, RUNS_URL} <= paths
    assert "/telemetry/report" in paths
    assert not any("telemetry" in name for name in _imports(REPO / "services" / "reporting" / "router.py"))


@pytest.mark.usefixtures("prefect_server")
def test_manual_run_end_to_end_runs_the_flow_and_feeds_the_other_two_endpoints(admin_client, week_of_activity):
    # Sin sustituir nada del pipeline: la BackgroundTask ejecuta el flow real de data/pipelines/.
    response = admin_client.post(RUNS_URL, json={"week_start": WEEK.isoformat(), "lookback_weeks": 0})
    assert response.status_code == 202

    latest = admin_client.get(LATEST_URL).json()["latest_run"]
    assert (latest["status"], latest["trigger"], latest["rows_upserted"]) == ("completed", "manual", 3)
    assert latest["triggered_by"]
    kpis = admin_client.get(KPI_URL, params={"week_start": WEEK.isoformat()}).json()
    assert len(kpis["entries"]) == 3
