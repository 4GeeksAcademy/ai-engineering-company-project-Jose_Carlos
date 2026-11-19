"""Fixtures de la cola de tareas (hito 22).

- `dlq_db`: SQLite en memoria con `task_dead_letters`, inyectado como motor de la DLQ.
- `celery_worker`: un worker **real** de Celery en un hilo (`celery.contrib.testing`), con el
  broker `memory://` y el backend `cache+memory://` del conftest global. Los mensajes pasan por
  el broker y los reintentos esperan su countdown como en producción; solo cambia el transporte.
- Las tareas de prueba están en `sample_tasks.py`.
"""

import time

import pytest
from celery.contrib.testing.worker import start_worker
from sqlalchemy.pool import StaticPool
from sqlmodel import create_engine

from services.celery_app import app
from services.tasks import dead_letters
from tests.tasks import sample_tasks  # noqa: F401 - registra las tareas de prueba antes del worker


@pytest.fixture
def dlq_db(monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    dead_letters.ensure_dead_letter_table(engine)
    monkeypatch.setattr(dead_letters, "dead_letter_engine", lambda: engine)
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def celery_worker():
    with start_worker(app, pool="solo", concurrency=1, perform_ping_check=False, loglevel="INFO",
                      shutdown_timeout=10) as worker:
        yield worker


def wait_for(result, timeout: float = 15):
    """Espera a que la tarea termine (SUCCESS o FAILURE) sin lanzar su excepción."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if result.state in ("SUCCESS", "FAILURE"):
            return result.state
        time.sleep(0.02)
    raise AssertionError(f"la tarea {result.id} sigue en {result.state} tras {timeout} s")
