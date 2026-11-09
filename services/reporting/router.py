"""Reporting de negocio (hito 19): los tres endpoints del pipeline weekly_warehouse_client_performance.

Módulo propio, separado de services/telemetry/ y de GET /telemetry/report. Aquí no hay ETL ni
Pandas: cada endpoint valida, autoriza y llama a UNA función de
data/pipelines/weekly_warehouse_client_performance/ (PIPELINE_DESIGN.md §11.3):

    GET  /reporting/weekly-warehouse-client-performance → queries.get_weekly_performance
    GET  /reporting/pipeline-runs/latest                → run_log.get_latest_run
    POST /reporting/pipeline-runs                       → trigger.trigger_manual_run

Mismas convenciones que el resto de la API: JWT (`get_current_user`), `require_admin` para la
acción que lanza trabajo, rutas síncronas (FastAPI las ejecuta en el threadpool), `{"detail": …}`
en los errores y 503 si Supabase no responde.
"""

import logging
from datetime import date

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.exc import SQLAlchemyError

from data.pipelines.weekly_warehouse_client_performance import config, connections, queries, run_log, trigger
from services.api.cache import make_key, response_cache
from services.api.security import get_current_user, require_admin
from services.reporting.schemas import (
    LatestPipelineRun, PipelineRunRequest, PipelineRunScheduled, WeeklyPerformanceReport,
)

logger = logging.getLogger("api.reporting")

router = APIRouter(prefix="/reporting", tags=["reporting"])

KPI_PATH = "/reporting/weekly-warehouse-client-performance"
# Las filas solo cambian cuando termina una corrida (una vez por semana): 5 minutos de caché no
# esconden nada relevante, y `computed_at` dice cuándo se calcularon.
KPI_TTL_SECONDS = 300


def _storage_unavailable(error: SQLAlchemyError) -> HTTPException:
    logger.error("reporting_storage_failed error=%s", type(error).__name__)
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Reporting storage unavailable")


def _parse_monday(value: str | None, field: str) -> date | None:
    if value is None:
        return None
    try:
        day = date.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=f"{field} debe ser YYYY-MM-DD")
    if day.weekday() != 0:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=f"{field} debe ser lunes")
    return day


def _weekly_report(week_start: date | None) -> dict:
    report = queries.get_weekly_performance(connections.api_engine(), week_start)
    if report is None:
        detail = "No hay datos para esa semana" if week_start else "Todavía no hay ninguna semana calculada"
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
    return report


@router.get("/weekly-warehouse-client-performance", response_model=WeeklyPerformanceReport)
def weekly_warehouse_client_performance(
    week_start: str | None = Query(None, description="Lunes de la semana (YYYY-MM-DD). Por defecto, la más reciente calculada."),
    _user: dict = Depends(get_current_user),
):
    """Consulta de KPIs: todas las combinaciones almacén/cliente de una semana (feed del dashboard)."""
    week = _parse_monday(week_start, "week_start")
    key = make_key(KPI_PATH, {"week_start": week.isoformat() if week else None})
    try:
        return response_cache.get_or_set(key, KPI_TTL_SECONDS, lambda: _weekly_report(week))
    except SQLAlchemyError as error:
        raise _storage_unavailable(error)


@router.get("/pipeline-runs/latest", response_model=LatestPipelineRun)
def latest_pipeline_run(
    pipeline: str = Query(config.PIPELINE_NAME, description="Nombre del pipeline."),
    _user: dict = Depends(get_current_user),
):
    """Consulta de estado: la última corrida (inicio, fin, estado, registros procesados, errores)."""
    try:
        engine = connections.api_engine()
        latest = run_log.get_latest_run(engine, pipeline) if queries.reporting_ready(engine) else None
    except SQLAlchemyError as error:
        raise _storage_unavailable(error)
    if latest is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="El pipeline no ha corrido nunca")
    return latest


@router.post("/pipeline-runs", response_model=PipelineRunScheduled, status_code=status.HTTP_202_ACCEPTED)
def create_pipeline_run(
    background_tasks: BackgroundTasks,
    body: PipelineRunRequest | None = None,
    admin: dict = Depends(require_admin),
):
    """Disparo manual: programa una corrida del flow y responde 202 sin esperar a que termine."""
    body = body or PipelineRunRequest()
    week = _parse_monday(body.week_start, "week_start")
    try:
        return trigger.trigger_manual_run(
            connections.api_engine(),
            week_start=week,
            lookback_weeks=body.lookback_weeks,
            triggered_by=admin["id"],
            schedule=background_tasks.add_task,
        )
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error))
    except run_log.PipelineAlreadyRunning as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))
    except trigger.TriggerUnavailable as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error))
    except SQLAlchemyError as error:
        raise _storage_unavailable(error)
