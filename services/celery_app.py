"""Instancia de Celery de TrackFlow (hito 22, ticket #DEV-55).

Productor / consumidor:

    Cliente → API (productor) → Redis (broker) → worker (consumidor) → Redis (resultado)

- La API importa este módulo solo para **encolar** (`task.apply_async`) y para leer el estado de
  una tarea (`AsyncResult`). Nunca ejecuta tareas.
- El worker es un proceso aparte:

      celery -A services.celery_app worker --loglevel=INFO               # Linux / Docker
      celery -A services.celery_app worker --loglevel=INFO --pool=solo   # Windows

- Flower, para ver la cola en desarrollo: `celery -A services.celery_app flower --port=5555`.

Redis es a la vez broker y backend de resultados, y la URL sale de `REDIS_URL` (la misma para
la API y para los workers). Este módulo no importa FastAPI ni la configuración de la API.

Las tres reglas del patrón, en la configuración:

1. **Mensajes ligeros**: serializador JSON y solo identificadores en los argumentos (cada tarea
   recupera ella misma los datos).
2. **ACK solo tras éxito**: `task_acks_late` + `task_reject_on_worker_lost`. Si el worker muere a
   mitad de una tarea, el mensaje vuelve a la cola.
3. **Toda tarea tiene timeout**: `task_soft_time_limit` / `task_time_limit` (por defecto 30 y 32
   minutos; las tareas pueden fijar los suyos).
"""

import os
from pathlib import Path

from celery import Celery
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(REPO_ROOT / ".env", override=False)  # el entorno (Docker) tiene prioridad

REDIS_URL_ENV = "REDIS_URL"
DEFAULT_REDIS_URL = "redis://localhost:6379/0"


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name, "").strip()
    return int(value) if value else default


def redis_url() -> str:
    return os.getenv(REDIS_URL_ENV, "").strip() or DEFAULT_REDIS_URL


SOFT_TIME_LIMIT_SECONDS = _int_env("CELERY_TASK_SOFT_TIME_LIMIT_SECONDS", 30 * 60)
TIME_LIMIT_SECONDS = _int_env("CELERY_TASK_TIME_LIMIT_SECONDS", SOFT_TIME_LIMIT_SECONDS + 120)
# Cuánto se guardan en Redis el estado y el resultado de cada tarea (GET /tasks/{task_id}).
RESULT_EXPIRES_SECONDS = _int_env("CELERY_RESULT_EXPIRES_SECONDS", 24 * 60 * 60)

# `include`: los módulos de tareas que carga el worker al arrancar.
TASK_MODULES = ["services.tasks.reporting"]

# Solo para los tests (broker `memory://` y backend `cache+memory://`, sin Redis): en el resto de
# casos no se definen y broker y backend son REDIS_URL.
BROKER_URL = os.getenv("CELERY_BROKER_URL", "").strip() or redis_url()
RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "").strip() or redis_url()

app = Celery("trackflow", broker=BROKER_URL, backend=RESULT_BACKEND, include=TASK_MODULES)

app.conf.update(
    # Mensajes: solo JSON (nada de pickle, que ejecutaría código al leer un mensaje).
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # Estados reales: STARTED se registra cuando un worker toma la tarea.
    task_track_started=True,
    # Guarda también nombre, argumentos, reintentos y worker junto al resultado.
    result_extended=True,
    result_expires=RESULT_EXPIRES_SECONDS,
    # ACK solo tras terminar: si el worker muere, el mensaje se reentrega.
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # Cada proceso del worker reserva un solo mensaje: una tarea larga no retiene otras en su buffer.
    worker_prefetch_multiplier=1,
    task_soft_time_limit=SOFT_TIME_LIMIT_SECONDS,
    task_time_limit=TIME_LIMIT_SECONDS,
    # Redis reentrega un mensaje sin ACK pasado este tiempo. Tiene que superar la tarea más larga
    # más su espera de reintento, o una tarea lenta se ejecutaría dos veces.
    broker_transport_options={"visibility_timeout": TIME_LIMIT_SECONDS + 30 * 60},
    broker_connection_retry_on_startup=True,
    # Al encolar desde la API: si Redis no responde, se falla rápido (503) en vez de colgar la petición.
    task_publish_retry_policy={"max_retries": 2, "interval_start": 0, "interval_step": 0.2, "interval_max": 0.5},
    redis_socket_connect_timeout=2,
    redis_socket_timeout=5,
    broker_connection_timeout=2,
    # Eventos para Flower: el worker avisa de cada tarea recibida, empezada, reintentada, terminada
    # o fallida, y la API avisa al encolarla (estado "sent" en Flower).
    worker_send_task_events=True,
    task_send_sent_event=True,
    # Los logs de las tareas (services.tasks) salen con el formato de Celery, que ya lleva fecha.
    worker_hijack_root_logger=True,
    worker_task_log_format="[%(asctime)s: %(levelname)s/%(processName)s] %(message)s",
)
