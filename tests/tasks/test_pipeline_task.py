"""La tarea del pipeline semanal en un worker real de Celery (hito 22).

El ETL ya no corre en la API: POST /reporting/pipeline-runs encola y el worker (otro hilo aquí,
otro proceso en Docker) ejecuta el flow real de data/pipelines/ contra el SQLite de la fixture.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

import services.api.main as main
from data.pipelines import pipeline
from services.api import user_service
from services.api.security import create_access_token
from services.api.user_models import UserRole
from services.celery_app import app
from services.tasks import dead_letters, registry
from services.tasks.reporting import TASK_NAME, run_weekly_performance_pipeline
from tests.reporting.conftest import WEEK, prefect_server, reporting_db, week_of_activity  # noqa: F401
from tests.tasks.conftest import wait_for

pytestmark = pytest.mark.usefixtures("celery_worker")


@pytest.fixture(scope="module")
def admin():
    user, _ = user_service.create_user(f"tasks-admin-{uuid.uuid4().hex[:8]}@trackflow.com", "admin-password",
                                       role=UserRole.ADMIN)
    return user


@pytest.fixture
def admin_client(admin):
    return TestClient(main.app, headers={"Authorization": f"Bearer {create_access_token(admin['id'])}"})


def test_the_worker_knows_the_pipeline_task():
    assert TASK_NAME in app.tasks
    assert app.tasks[TASK_NAME].max_retries == 3


@pytest.mark.usefixtures("prefect_server")
def test_the_endpoint_enqueues_and_the_worker_runs_the_real_flow(admin, admin_client, week_of_activity, dlq_db):
    response = admin_client.post("/reporting/pipeline-runs", json={"week_start": WEEK.isoformat(), "lookback_weeks": 0})
    assert response.status_code == 202
    task_id = response.json()["task_id"]
    assert registry.lookup(task_id)["owner_id"] == admin["id"]

    result = app.AsyncResult(task_id)
    assert wait_for(result, timeout=120) == "SUCCESS", result.traceback
    summary = result.result
    assert summary["weeks_processed"] == [WEEK.isoformat()]
    assert summary["rows_upserted"] == 3
    assert uuid.UUID(summary["run_id"])

    # El flow escribió lo mismo que antes escribían las BackgroundTasks.
    latest = admin_client.get("/reporting/pipeline-runs/latest").json()["latest_run"]
    assert (latest["status"], latest["trigger"], latest["rows_upserted"]) == ("completed", "manual", 3)
    assert latest["triggered_by"] == admin["id"]
    assert len(admin_client.get("/reporting/weekly-warehouse-client-performance",
                                params={"week_start": WEEK.isoformat()}).json()["entries"]) == 3
    assert dead_letters.list_dead_letters(dlq_db) == []


def test_a_pipeline_that_keeps_failing_ends_in_the_dead_letter_queue(dlq_db, monkeypatch):
    calls = []

    def failing_flow(**kwargs):
        calls.append(kwargs)
        raise pipeline.PipelineStageError("extract", "OperationalError: la base no responde")

    monkeypatch.setattr(pipeline, "weekly_warehouse_client_performance_flow", failing_flow)
    result = run_weekly_performance_pipeline.delay(week_start=WEEK.isoformat(), lookback_weeks=0, triggered_by="admin-1")
    assert wait_for(result) == "FAILURE"
    assert len(calls) == 4  # 1 + 3 reintentos

    letter = dead_letters.get_dead_letter(dlq_db, result.id)
    assert (letter["task_name"], letter["attempt"], letter["error_type"]) == (TASK_NAME, 4, "PipelineStageError")
    assert "extract: OperationalError: la base no responde" in letter["error_message"]
    assert letter["kwargs"] == {"week_start": WEEK.isoformat(), "lookback_weeks": 0, "triggered_by": "admin-1"}


def test_an_invalid_parameter_is_not_retried(dlq_db, monkeypatch):
    calls = []
    monkeypatch.setattr(pipeline, "weekly_warehouse_client_performance_flow", lambda **kwargs: calls.append(kwargs))
    result = run_weekly_performance_pipeline.delay(week_start="no-es-fecha")
    assert wait_for(result) == "FAILURE"
    assert calls == []  # date.fromisoformat falla antes del flow
    assert dead_letters.get_dead_letter(dlq_db, result.id)["attempt"] == 1
