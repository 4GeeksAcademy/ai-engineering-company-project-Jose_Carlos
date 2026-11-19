"""GET /tasks/{task_id}: estado y resultado de una tarea encolada (hito 22, ticket #DEV-55).

Lee el estado que el worker guarda en Redis (backend de resultados de Celery). No espera nunca a
la tarea: responde al instante con lo que haya.

    {"task_id": "...", "status": "pending|started|retry|success|failure", "result": ..., ...}

- `status` es el estado real de Celery en minúsculas. Además de los cuatro del ticket aparece
  `retry` (estado RETRY de Celery): la tarea falló y espera su backoff para el siguiente intento.
- `result`: el valor devuelto por la tarea, solo en `success`. En `failure` y `retry`, `error`
  lleva el tipo y el mensaje.
- 404 si el id no lo encoló la API (Celery diría `PENDING` para cualquier id inventado) o si es
  de otro usuario y quien pregunta no es admin. 503 si Redis no responde.

Es el único módulo de services/tasks que importa FastAPI: el worker no lo carga.
"""

import logging
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from services.api.security import get_current_user, is_admin
from services.celery_app import app
from services.tasks import registry

logger = logging.getLogger("api.tasks")

router = APIRouter(prefix="/tasks", tags=["tasks"])

TaskState = Literal["pending", "started", "retry", "success", "failure"]

# Estados de Celery → `status` de la respuesta.
CELERY_STATES: dict[str, TaskState] = {
    "PENDING": "pending",    # en la cola (o con ETA, esperando)
    "RECEIVED": "pending",   # un worker la reservó pero aún no la ha empezado
    "STARTED": "started",    # un worker la está ejecutando (task_track_started)
    "RETRY": "retry",        # falló y espera su reintento con backoff
    "SUCCESS": "success",
    "FAILURE": "failure",    # agotó los reintentos o el error no se reintenta: está en la DLQ
    "REVOKED": "failure",    # cancelada
}


class TaskStatus(BaseModel):
    task_id: str
    status: TaskState
    result: Any = Field(None, description="Lo que devolvió la tarea (solo con status success).")
    error: str | None = Field(None, description="Tipo y mensaje del último error (failure / retry).")
    attempt: int | None = Field(None, description="Intento en curso o último intento (1 = el primero).")
    max_attempts: int | None = None
    task_name: str
    enqueued_at: str
    finished_at: str | None = None


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tarea no encontrada")


def _unavailable(error: Exception) -> HTTPException:
    logger.error("task_backend_unavailable error=%s", type(error).__name__)
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="La cola de tareas no responde")


@router.get("/{task_id}", response_model=TaskStatus)
def get_task_status(task_id: str, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """Estado actual de la tarea y su resultado cuando esté disponible."""
    try:
        task_id = str(uuid.UUID(task_id))
    except ValueError:
        raise _not_found()
    try:
        entry = registry.lookup(task_id)
        if entry is None or (entry["owner_id"] != user["id"] and not is_admin(user)):
            raise _not_found()
        meta = app.backend.get_task_meta(task_id)  # una sola lectura de Redis: estado, resultado, reintentos
        state = meta.get("status", "PENDING")
    except HTTPException:
        raise
    except Exception as error:  # noqa: BLE001 - Redis caído o mal configurado
        raise _unavailable(error)

    task = app.tasks.get(entry["task_name"])
    max_attempts = (task.max_retries + 1) if task is not None and task.max_retries is not None else None
    retries = meta.get("retries")
    info = meta.get("result")
    status_value = CELERY_STATES.get(state, "pending")
    finished = meta.get("date_done") if status_value in ("success", "failure") else None
    return {
        "task_id": task_id,
        "status": status_value,
        "result": info if status_value == "success" else None,
        "error": _error_text(info) if status_value in ("failure", "retry") else None,
        "attempt": retries + 1 if isinstance(retries, int) else None,
        "max_attempts": max_attempts,
        "task_name": entry["task_name"],
        "enqueued_at": entry["enqueued_at"],
        "finished_at": finished.isoformat() if hasattr(finished, "isoformat") else finished,
    }


def _error_text(info: Any) -> str | None:
    """`meta.result` de un fallo: el dict serializado de la excepción (o la excepción ya rehecha)."""
    if info is None:
        return None
    if isinstance(info, dict) and "exc_message" in info:
        message = info.get("exc_message")
        message = " ".join(map(str, message)) if isinstance(message, (list, tuple)) else str(message)
        return f"{info.get('exc_type', 'Error')}: {message}"
    if isinstance(info, BaseException):
        return f"{type(info).__name__}: {info}"
    return str(info)
