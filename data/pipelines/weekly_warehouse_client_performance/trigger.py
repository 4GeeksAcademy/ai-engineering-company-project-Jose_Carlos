"""Disparo manual del flow desde la API (POST /reporting/pipeline-runs, PIPELINE_DESIGN.md §11.2).

La API nunca ejecuta el ETL, ni dentro de la petición ni en su proceso. Dos modos, según
`REPORTING_TRIGGER_MODE`:

- `celery` (por defecto, hito 22): entrega los parámetros a `enqueue` —en la API, la tarea de
  Celery `services.tasks.reporting.run_weekly_performance_pipeline`— y vuelve al instante con su
  `task_id`. La ejecuta un worker de Celery, en otro proceso. Este módulo no importa Celery:
  recibe la función que encola.
- `deployment` (con servidor de Prefect y worker de Prefect): `run_deployment(..., timeout=0)`
  **programa** una corrida del deployment `weekly-warehouse-client-performance/weekly-monday` y
  vuelve al instante con su `flow_run_id`.

El modo `local` de los hitos 19-20 (BackgroundTasks de FastAPI, que ejecutaban el flow dentro del
proceso de la API) ya no existe: se rechaza con un mensaje que explica el cambio.

En los dos casos se valida antes: semana lunes y no futura, `lookback_weeks` en rango y que no
haya otra corrida en curso (409). La propia corrida lo vuelve a comprobar al arrancar (índice
único parcial de reporting.pipeline_runs), así que dos disparos simultáneos no pueden solaparse.
"""

import logging
import os
from datetime import date
from typing import Any, Callable

from sqlalchemy.engine import Engine

from . import config, queries, run_log

logger = logging.getLogger("pipelines.weekly_warehouse_client_performance")

MODE_ENV = "REPORTING_TRIGGER_MODE"
MODES = ("celery", "deployment")
DEFAULT_MODE = "celery"


class TriggerUnavailable(RuntimeError):
    """No se pudo programar la corrida (servidor de Prefect caído o deployment inexistente)."""


def trigger_mode() -> str:
    mode = os.getenv(MODE_ENV, DEFAULT_MODE).strip().lower() or DEFAULT_MODE
    if mode == "local":
        raise TriggerUnavailable(
            f"{MODE_ENV}=local ya no existe (hito 22): la corrida se encola en Celery. "
            f"Usa {MODE_ENV}=celery (o déjalo vacío) y levanta un worker"
        )
    if mode not in MODES:
        raise TriggerUnavailable(f"{MODE_ENV} debe ser uno de {MODES}")
    return mode


def validate_request(week_start: date | None, lookback_weeks: int, today: date) -> None:
    if week_start is not None:
        if week_start.weekday() != 0:
            raise ValueError("week_start debe ser lunes")
        if week_start > config.week_monday(today):
            raise ValueError("week_start no puede ser una semana futura")
    if not 0 <= lookback_weeks <= config.MAX_LOOKBACK_WEEKS:
        raise ValueError(f"lookback_weeks debe estar entre 0 y {config.MAX_LOOKBACK_WEEKS}")


def _flow_parameters(week_start: date | None, lookback_weeks: int, triggered_by: str) -> dict[str, Any]:
    return {"week_start": week_start, "lookback_weeks": lookback_weeks, "trigger": "manual", "triggered_by": triggered_by}


def trigger_manual_run(
    engine: Engine,
    *,
    week_start: date | None,
    lookback_weeks: int,
    triggered_by: str,
    enqueue: Callable[[dict[str, Any]], str] | None = None,
) -> dict[str, Any]:
    """Programa una corrida manual y devuelve `{pipeline_name, status, mode, flow_run_id, task_id}`.

    `enqueue(parameters) -> task_id` encola la corrida (modo celery). Lanza `ValueError`
    (parámetros), `run_log.PipelineAlreadyRunning` (otra en curso) o `TriggerUnavailable` (no se
    pudo programar: Redis o Prefect caídos).
    """
    validate_request(week_start, lookback_weeks, config.utc_now().date())
    if queries.reporting_ready(engine) and run_log.is_running(engine):
        raise run_log.PipelineAlreadyRunning(f"ya hay una corrida en curso de {config.PIPELINE_NAME}")

    mode = trigger_mode()
    parameters = _flow_parameters(week_start, lookback_weeks, triggered_by)
    if mode == "deployment":
        try:
            from prefect.deployments import run_deployment

            flow_run = run_deployment(config.DEPLOYMENT_NAME, parameters=parameters, timeout=0)
        except Exception as error:  # noqa: BLE001 - red, servidor caído o deployment inexistente
            raise TriggerUnavailable(f"no se pudo programar la corrida: {type(error).__name__}") from error
        flow_run_id, task_id = str(flow_run.id), None
    else:
        if enqueue is None:
            raise TriggerUnavailable("modo celery sin función para encolar la corrida")
        try:
            task_id = enqueue(parameters)
        except Exception as error:  # noqa: BLE001 - Redis caído o mal configurado
            raise TriggerUnavailable(f"no se pudo encolar la corrida: {type(error).__name__}") from error
        flow_run_id = None  # lo asigna Prefect cuando el worker arranca el flow; está en el resultado de la tarea

    logger.info("manual run scheduled mode=%s by=%s week_start=%s task_id=%s", mode, triggered_by, week_start, task_id)
    return {"pipeline_name": config.PIPELINE_NAME, "status": "scheduled", "mode": mode,
            "flow_run_id": flow_run_id, "task_id": task_id}
