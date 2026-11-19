"""Configuración de la instancia de Celery y de la DLQ (hito 22)."""

import os
import subprocess
import sys

from sqlalchemy import inspect
from sqlmodel import create_engine

from services import celery_app
from services.tasks import dead_letters


def test_broker_and_result_backend_come_from_redis_url(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://broker.test:6379/3")
    assert celery_app.redis_url() == "redis://broker.test:6379/3"
    monkeypatch.delenv("REDIS_URL")
    assert celery_app.redis_url() == "redis://localhost:6379/0"


def test_the_app_follows_the_three_rules_of_the_pattern():
    conf = celery_app.app.conf
    # 1. Mensajes ligeros y seguros: solo JSON.
    assert conf.task_serializer == "json" and conf.accept_content == ["json"]
    # 2. ACK solo tras éxito: si el worker muere, el mensaje vuelve a la cola.
    assert conf.task_acks_late is True and conf.task_reject_on_worker_lost is True
    assert conf.worker_prefetch_multiplier == 1
    # 3. Toda tarea tiene timeout.
    assert 0 < conf.task_soft_time_limit < conf.task_time_limit
    # Redis no reentrega una tarea larga mientras sigue en marcha.
    assert conf.broker_transport_options["visibility_timeout"] > conf.task_time_limit
    # Estados reales, con STARTED.
    assert conf.task_track_started is True


def test_celery_app_does_not_import_fastapi_or_the_api():
    code = (
        "import sys; import services.celery_app, services.tasks.base, services.tasks.dead_letters; "
        "bad = [m for m in sys.modules if m == 'fastapi' or m.startswith('services.api')]; "
        "print(bad); sys.exit(1 if bad else 0)"
    )
    env = {**os.environ, "PYTHONPATH": str(celery_app.REPO_ROOT)}
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env,
                            cwd=celery_app.REPO_ROOT)
    assert result.returncode == 0, result.stdout + result.stderr


def test_dead_letter_table_has_the_required_columns():
    engine = create_engine("sqlite://")
    dead_letters.ensure_dead_letter_table(engine)
    dead_letters.ensure_dead_letter_table(engine)  # idempotente
    columns = {column["name"] for column in inspect(engine).get_columns("task_dead_letters")}
    assert {"task_id", "task_name", "attempt", "error_type", "error_message", "failed_at", "args", "kwargs"} <= columns
    indexes = {index["name"]: index for index in inspect(engine).get_indexes("task_dead_letters")}
    assert indexes["ux_task_dead_letters_task_id"]["unique"]


def test_the_postgres_migration_matches_the_table():
    sql = dead_letters.SCHEMA_SQL.read_text(encoding="utf-8")
    for column in dead_letters.task_dead_letters.columns:
        assert f"  {column.name} " in sql, column.name
    assert "create unique index if not exists ux_task_dead_letters_task_id" in sql
    assert "enable row level security" in sql


def test_the_dead_letter_queue_uses_tasks_database_url_first(monkeypatch, tmp_path):
    dead_letters.dead_letter_engine.cache_clear()
    monkeypatch.setenv(dead_letters.URL_ENV, f"sqlite:///{tmp_path / 'dlq.db'}")
    try:
        assert dead_letters.dead_letter_engine().url.database.endswith("dlq.db")
    finally:
        dead_letters.dead_letter_engine.cache_clear()
