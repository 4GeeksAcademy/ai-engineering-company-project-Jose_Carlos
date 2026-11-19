"""Registro de las tareas que encoló la API: quién la pidió y cuándo.

Celery responde `PENDING` para **cualquier** id que no conozca, también para uno inventado. Para
que GET /tasks/{task_id} distinga «en cola» de «no existe» (y para que un usuario no consulte las
tareas de otro), la API guarda una entrada por tarea en el mismo backend de resultados (Redis)
**antes** de encolarla, con la misma caducidad que el resultado.

Es una clave aparte del resultado de Celery: si la API escribiese en la clave del resultado,
podría pisar un STARTED que el worker ya hubiera guardado.
"""

import json
from datetime import datetime, timezone
from typing import Any

from services.celery_app import app

KEY_PREFIX = "trackflow-task-registry-"


def _key(task_id: str) -> str:
    return f"{KEY_PREFIX}{task_id}"


def register(task_id: str, *, task_name: str, owner_id: str) -> dict[str, Any]:
    entry = {
        "task_id": task_id,
        "task_name": task_name,
        "owner_id": owner_id,
        "enqueued_at": datetime.now(timezone.utc).isoformat(),
    }
    app.backend.set(_key(task_id), json.dumps(entry))
    return entry


def lookup(task_id: str) -> dict[str, Any] | None:
    raw = app.backend.get(_key(task_id))
    if raw is None:
        return None
    return json.loads(raw.decode() if isinstance(raw, bytes) else raw)


def forget(task_id: str) -> None:
    """Borra la entrada (la API la usa si no pudo encolar la tarea)."""
    app.backend.delete(_key(task_id))
