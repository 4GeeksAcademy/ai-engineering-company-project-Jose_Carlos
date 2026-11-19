"""Tarea asíncrona del pipeline semanal de desempeño de negocio (hito 22, ticket #DEV-55).

Es la operación más pesada de la API: `POST /reporting/pipeline-runs` lanza el ETL completo
(extracción de `telemetry_events`, transformación con Pandas y carga en `reporting.*`, unos 25 s
con pocos datos y minutos con un histórico real). Hasta el hito 21 se ejecutaba en las
BackgroundTasks de FastAPI, es decir, **dentro del proceso de la API**. Ahora:

    API  ── enqueue_weekly_performance_run() ──►  Redis  ──►  worker: run_weekly_performance_pipeline

- **Mensaje ligero**: solo `week_start` (una fecha), `lookback_weeks` (un entero) y
  `triggered_by` (el id del admin). El worker lee él mismo los eventos de la base.
- **Reintentos**: los de `TrackedTask` (3, con backoff 10/20/40 s). El flow ya reintenta por su
  cuenta los errores transitorios de cada task (hito 19); el reintento de Celery cubre la
  corrida entera (p. ej. la base caída más tiempo del que aguantan esos reintentos).
- **Timeout**: 30 minutos (soft) y 32 (hard), los de `services/celery_app.py`.
- El flow se importa dentro de la tarea: la API importa este módulo para encolar y no carga
  Prefect ni Pandas.
"""

import json
import uuid
from datetime import date
from typing import Any

from celery.exceptions import SoftTimeLimitExceeded

from services.celery_app import app
from services.tasks import registry
from services.tasks.base import TrackedTask

TASK_NAME = "reporting.run_weekly_performance_pipeline"


@app.task(bind=True, base=TrackedTask, name=TASK_NAME, dont_retry_on=(ValueError, SoftTimeLimitExceeded))
def run_weekly_performance_pipeline(
    self,
    week_start: str | None = None,
    lookback_weeks: int | None = None,
    triggered_by: str | None = None,
) -> dict[str, Any]:
    """Ejecuta el flow `weekly_warehouse_client_performance` y devuelve su resumen.

    Un fallo de una etapa crítica llega como `PipelineStageError` (ya registrado en
    `reporting.pipeline_runs`) y se reintenta; un parámetro inválido (`ValueError`), no.
    """
    from data.pipelines import pipeline  # Prefect y Pandas solo en el worker
    from data.pipelines.weekly_warehouse_client_performance import config

    summary = pipeline.weekly_warehouse_client_performance_flow(
        week_start=date.fromisoformat(week_start) if week_start else None,
        lookback_weeks=config.DEFAULT_LOOKBACK_WEEKS if lookback_weeks is None else lookback_weeks,
        trigger="manual",
        triggered_by=triggered_by,
    )
    # El resultado viaja por JSON hasta Redis: fechas y UUID como texto.
    return json.loads(json.dumps(summary, default=str))


def enqueue_weekly_performance_run(parameters: dict[str, Any], *, owner_id: str) -> str:
    """Encola la corrida y devuelve su `task_id`. Lo usa `trigger.trigger_manual_run` en la API.

    Primero registra la tarea (para que GET /tasks/{task_id} la reconozca desde el primer
    instante) y después publica el mensaje. Si Redis no responde, lanza la excepción.
    """
    week_start = parameters.get("week_start")
    kwargs = {
        "week_start": week_start.isoformat() if isinstance(week_start, date) else week_start,
        "lookback_weeks": parameters.get("lookback_weeks"),
        "triggered_by": parameters.get("triggered_by"),
    }
    task_id = str(uuid.uuid4())
    registry.register(task_id, task_name=TASK_NAME, owner_id=owner_id)
    try:
        run_weekly_performance_pipeline.apply_async(kwargs=kwargs, task_id=task_id)
    except Exception:
        try:
            registry.forget(task_id)
        except Exception:  # noqa: BLE001 - Redis caído: la entrada caduca sola
            pass
        raise
    return task_id
