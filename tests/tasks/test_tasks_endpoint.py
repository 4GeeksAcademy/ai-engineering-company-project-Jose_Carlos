"""GET /tasks/{task_id} en cada fase del ciclo de vida de una tarea (hito 22).

Con un worker real: pending (en cola con ETA), started (ejecutándose), retry (esperando su
backoff), success (con resultado) y failure (con el error, y la tarea en la DLQ).
"""

import time
import uuid

import pytest
from fastapi.testclient import TestClient

import services.api.main as main
from services.api import user_service
from services.api.security import create_access_token
from services.api.user_models import UserRole
from services.tasks import base, registry
from tests.tasks.conftest import wait_for
from tests.tasks.sample_tasks import always_fails, flaky, slow

pytestmark = pytest.mark.usefixtures("celery_worker", "dlq_db")


def make_user(role: UserRole = UserRole.USER) -> dict:
    user, _ = user_service.create_user(f"tasks-{uuid.uuid4().hex[:8]}@trackflow.com", "tasks-password", role=role)
    return user


def client_for(user: dict) -> TestClient:
    return TestClient(main.app, headers={"Authorization": f"Bearer {create_access_token(user['id'])}"})


@pytest.fixture(scope="module")
def owner():
    return make_user()


@pytest.fixture
def owner_client(owner):
    return client_for(owner)


def enqueue(task, *args, owner_id: str, **options):
    """Lo mismo que hace la API: registrar la tarea y publicarla."""
    task_id = str(uuid.uuid4())
    registry.register(task_id, task_name=task.name, owner_id=owner_id)
    return task.apply_async(args=args, task_id=task_id, **options)


def poll_until(client, task_id: str, wanted: str, timeout: float = 10) -> dict:
    deadline = time.monotonic() + timeout
    seen = []
    while time.monotonic() < deadline:
        body = client.get(f"/tasks/{task_id}").json()
        seen.append(body.get("status"))
        if body.get("status") == wanted:
            return body
        time.sleep(0.02)
    raise AssertionError(f"nunca llegó a {wanted}; estados vistos: {sorted(set(seen))}")


def test_a_queued_task_is_pending(owner, owner_client):
    result = enqueue(flaky, uuid.uuid4().hex, 0, owner_id=owner["id"], countdown=30)  # en cola 30 s
    response = owner_client.get(f"/tasks/{result.id}")
    assert response.status_code == 200
    body = response.json()
    assert (body["task_id"], body["status"], body["result"], body["error"]) == (result.id, "pending", None, None)
    assert body["task_name"] == "tests.flaky" and body["enqueued_at"]
    result.revoke()


def test_a_running_task_is_started(owner, owner_client):
    result = enqueue(slow, uuid.uuid4().hex, 1.0, owner_id=owner["id"])
    body = poll_until(owner_client, result.id, "started")
    assert body["attempt"] == 1 and body["max_attempts"] == 4
    assert body["result"] is None
    wait_for(result)


def test_a_task_waiting_for_its_backoff_is_retry(owner, owner_client, monkeypatch):
    monkeypatch.setenv(base.RETRY_BACKOFF_ENV, "1")  # 1 s de espera: tiempo de verlo
    result = enqueue(flaky, uuid.uuid4().hex, 1, owner_id=owner["id"])
    body = poll_until(owner_client, result.id, "retry")
    assert "Boom: fallo simulado 1 de 1" in body["error"]
    assert body["attempt"] == 1
    assert wait_for(result) == "SUCCESS"


def test_a_finished_task_is_success_with_its_result(owner, owner_client):
    key = uuid.uuid4().hex
    result = enqueue(flaky, key, 0, owner_id=owner["id"])
    assert wait_for(result) == "SUCCESS"
    body = owner_client.get(f"/tasks/{result.id}").json()
    assert body["status"] == "success"
    assert body["result"] == {"key": key, "attempts": 1}
    assert body["error"] is None and body["finished_at"]


def test_a_task_that_exhausted_its_retries_is_failure_with_the_error(owner, owner_client):
    result = enqueue(always_fails, uuid.uuid4().hex, owner_id=owner["id"])
    assert wait_for(result) == "FAILURE"
    body = owner_client.get(f"/tasks/{result.id}").json()
    assert body["status"] == "failure"
    assert body["result"] is None
    assert "fallo permanente, intento 4" in body["error"]
    assert body["attempt"] == 4 and body["max_attempts"] == 4
    assert body["finished_at"]


def test_the_full_lifecycle_through_the_endpoint(owner, owner_client, monkeypatch):
    """pending → started → retry → started → success, visto solo a través de GET /tasks/{id}."""
    monkeypatch.setenv(base.RETRY_BACKOFF_ENV, "0.5")
    result = enqueue(flaky, uuid.uuid4().hex, 1, owner_id=owner["id"], countdown=0.5)
    seen = []
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and (not seen or seen[-1] != "success"):
        status = owner_client.get(f"/tasks/{result.id}").json()["status"]
        if not seen or seen[-1] != status:
            seen.append(status)
        time.sleep(0.01)
    assert seen[0] == "pending" and seen[-1] == "success"
    assert "retry" in seen


def test_an_unknown_task_id_is_404(owner_client):
    # Celery diría PENDING para cualquier id: el registro de la API distingue los que existen.
    assert owner_client.get(f"/tasks/{uuid.uuid4()}").status_code == 404
    assert owner_client.get("/tasks/no-es-un-uuid").status_code == 404


def test_another_users_task_is_404_but_an_admin_can_see_it(owner):
    result = enqueue(flaky, uuid.uuid4().hex, 0, owner_id=owner["id"])
    wait_for(result)
    assert client_for(make_user()).get(f"/tasks/{result.id}").status_code == 404
    assert client_for(make_user(UserRole.ADMIN)).get(f"/tasks/{result.id}").json()["status"] == "success"


def test_the_endpoint_requires_a_session(anon_client):
    assert anon_client.get(f"/tasks/{uuid.uuid4()}").status_code == 401


def test_the_endpoint_is_503_when_redis_is_down(owner_client, monkeypatch):
    def down(task_id):
        raise ConnectionError("redis down")

    monkeypatch.setattr(registry, "lookup", down)
    assert owner_client.get(f"/tasks/{uuid.uuid4()}").status_code == 503
