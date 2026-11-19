"""docker-compose.yml de la cola de tareas (hito 22): Redis, worker y Flower."""

from pathlib import Path

import yaml

COMPOSE = yaml.safe_load((Path(__file__).resolve().parents[2] / "docker-compose.yml").read_text(encoding="utf-8"))
SERVICES = COMPOSE["services"]


def test_redis_uses_the_official_image_port_6379_and_noeviction():
    redis = SERVICES["redis"]
    assert redis["image"].split(":")[0] == "redis"
    assert any(port.endswith(":6379") for port in redis["ports"])
    command = redis["command"]
    assert command[command.index("--maxmemory-policy") + 1] == "noeviction"
    assert command[command.index("--appendonly") + 1] == "yes"


def test_api_worker_and_flower_share_the_same_redis_url():
    urls = {name: SERVICES[name]["environment"]["REDIS_URL"] for name in ("backend", "worker", "flower")}
    assert len(set(urls.values())) == 1, urls
    for name in ("backend", "worker", "flower"):
        assert SERVICES[name]["depends_on"]["redis"]["condition"] == "service_healthy"


def test_the_worker_is_its_own_container_running_celery_not_uvicorn():
    worker = SERVICES["worker"]
    assert worker["command"][:4] == ["celery", "-A", "services.celery_app", "worker"]
    assert "uvicorn" not in " ".join(worker["command"])
    # La tarea importa data.pipelines después de cargar la app: /app siempre en el path.
    assert worker["environment"]["PYTHONPATH"] == "/app"
    assert "stop_grace_period" in worker


def test_flower_is_exposed_on_port_5555():
    flower = SERVICES["flower"]
    assert flower["command"][:4] == ["celery", "-A", "services.celery_app", "flower"]
    assert any(port.endswith(":5555") for port in flower["ports"])
