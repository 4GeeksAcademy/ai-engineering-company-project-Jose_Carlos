"""Disparo manual del flow desde la API (POST /reporting/pipeline-runs, PIPELINE_DESIGN.md §11.2).

La API nunca ejecuta el ETL dentro de la petición. Dos modos, según `REPORTING_TRIGGER_MODE`:

- `deployment` (producción, con servidor de Prefect y worker): `run_deployment(...,
  timeout=0)` **programa** una corrida del deployment `weekly-warehouse-client-performance/
  weekly-monday` y vuelve al instante con su `flow_run_id`. La ejecuta el worker.
- `local` (por defecto, desarrollo): entrega la corrida a `schedule` —en la API, las
  BackgroundTasks de FastAPI, que la ejecutan después de responder— y vuelve al instante.
  El flow es el mismo `data.pipelines.pipeline.weekly_warehouse_client_performance_flow`.

En los dos casos se valida antes: semana lunes y no futura, `lookback_weeks` en rango y que no
haya otra corrida en curso (409). La propia corrida lo vuelve a comprobar al arrancar (índice
único parcial de reporting.pipeline_runs), así que dos disparos simultáneos no pueden solaparse.
"""

import logging
import os
import threading
from datetime import date
from typing import Any, Callable

from sqlalchemy.engine import Engine

from . import config, queries, run_log

logger = logging.getLogger("pipelines.weekly_warehouse_client_performance")

MODE_ENV = "REPORTING_TRIGGER_MODE"
MODES = ("local", "deployment")


class TriggerUnavailable(RuntimeError):
    """No se pudo programar la corrida (servidor de Prefect caído o deployment inexistente)."""


def trigger_mode() -> str:
    mode = os.getenv(MODE_ENV, "local").strip().lower() or "local"
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


def run_locally(parameters: dict[str, Any]) -> None:
    """Ejecuta el flow en este proceso. Un fallo ya queda en reporting.pipeline_runs y en Prefect."""
    from data.pipelines import pipeline  # Prefect solo se importa cuando hace falta

    try:
        pipeline.weekly_warehouse_client_performance_flow(**parameters)
    except Exception as error:  # noqa: BLE001 - nadie espera esta excepción: se registra
        logger.error("manual run failed: %s", error)


def _in_thread(job: Callable[..., None], *args: Any) -> None:
    threading.Thread(target=job, args=args, name=f"{config.PIPELINE_NAME}-manual", daemon=True).start()


def trigger_manual_run(
    engine: Engine,
    *,
    week_start: date | None,
    lookback_weeks: int,
    triggered_by: str,
    schedule: Callable[..., None] | None = None,
) -> dict[str, Any]:
    """Programa una corrida manual y devuelve `{pipeline_name, status, mode, flow_run_id}`.

    Lanza `ValueError` (parámetros), `run_log.PipelineAlreadyRunning` (otra en curso) o
    `TriggerUnavailable` (no se pudo programar).
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
        flow_run_id = str(flow_run.id)
    else:
        (schedule or _in_thread)(run_locally, parameters)
        flow_run_id = None  # lo asigna Prefect al arrancar; se consulta en GET /reporting/pipeline-runs/latest

    logger.info("manual run scheduled mode=%s by=%s week_start=%s", mode, triggered_by, week_start)
    return {"pipeline_name": config.PIPELINE_NAME, "status": "scheduled", "mode": mode, "flow_run_id": flow_run_id}
