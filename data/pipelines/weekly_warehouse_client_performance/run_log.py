"""Log de ejecución en `reporting.pipeline_runs` (PIPELINE_DESIGN.md §9).

Una fila por corrida: hora de inicio y fin, estado, registros procesados, errores y la marca de
agua de la extracción. Cada escritura va en su **propia transacción**, separada de la de la
carga: si la carga hace ROLLBACK, el registro del fallo no se pierde con ella.

    start_run()                   status = running   (antes marca como `crashed` las corridas colgadas)
    finish_run()                  status = completed (con contadores y avisos)
    fail_run()                    status = failed    (con etapa y mensaje)
    last_successful_watermark()   `source_watermark` de la última corrida completed
    get_latest_run()              lo que sirve GET /reporting/pipeline-runs/latest
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from . import config
from .schema import pipeline_runs as RUNS

MAX_ERROR_MESSAGE = 2000
COUNTERS = ("events_extracted", "events_discarded", "events_deduplicated", "rows_upserted", "rows_deleted")


class PipelineAlreadyRunning(RuntimeError):
    """Ya hay una corrida `running` de este pipeline (índice único parcial ux_pipeline_runs_one_running)."""


def mark_stale_runs(engine: Engine, pipeline_name: str, now: datetime) -> int:
    """Corridas `running` que llevan más de STALE_RUN_AFTER: el proceso murió sin cerrarlas."""
    with engine.begin() as connection:
        result = connection.execute(
            update(RUNS)
            .where(
                RUNS.c.pipeline_name == pipeline_name,
                RUNS.c.status == "running",
                RUNS.c.started_at < now - config.STALE_RUN_AFTER,
            )
            .values(status="failed", finished_at=now, error_stage="crashed",
                    error_message=f"stale: sin terminar después de {config.STALE_RUN_AFTER}")
        )
    return result.rowcount


def start_run(
    engine: Engine,
    *,
    run_id: uuid.UUID,
    pipeline_name: str,
    trigger: str,
    triggered_by: str | None,
    started_at: datetime,
    source_watermark: datetime,
    parameters: dict[str, Any],
    code_version: str | None,
) -> None:
    mark_stale_runs(engine, pipeline_name, started_at)
    try:
        with engine.begin() as connection:
            connection.execute(RUNS.insert().values(
                run_id=run_id,
                pipeline_name=pipeline_name,
                trigger=trigger,
                triggered_by=triggered_by,
                status="running",
                started_at=started_at,
                source_watermark=source_watermark,
                weeks_processed=[],
                warnings=[],
                parameters=parameters,
                code_version=code_version,
            ))
    except IntegrityError as error:
        raise PipelineAlreadyRunning(f"ya hay una corrida en curso de {pipeline_name}") from error


def finish_run(engine: Engine, run_id: uuid.UUID, *, finished_at: datetime, weeks_processed: list[str],
               counters: dict[str, int], warnings: list[dict]) -> None:
    with engine.begin() as connection:
        connection.execute(
            update(RUNS).where(RUNS.c.run_id == run_id).values(
                status="completed", finished_at=finished_at, weeks_processed=weeks_processed,
                warnings=warnings, **{name: int(counters.get(name, 0)) for name in COUNTERS},
            )
        )


def fail_run(engine: Engine, run_id: uuid.UUID, *, finished_at: datetime, error_stage: str, error_message: str,
             weeks_processed: list[str] | None = None, counters: dict[str, int] | None = None,
             warnings: list[dict] | None = None) -> None:
    values: dict[str, Any] = {
        "status": "failed",
        "finished_at": finished_at,
        "error_stage": error_stage,
        "error_message": error_message[:MAX_ERROR_MESSAGE],
        **{name: int(value) for name, value in (counters or {}).items() if name in COUNTERS},
    }
    if weeks_processed is not None:
        values["weeks_processed"] = weeks_processed
    if warnings is not None:
        values["warnings"] = warnings
    with engine.begin() as connection:
        connection.execute(update(RUNS).where(RUNS.c.run_id == run_id, RUNS.c.status == "running").values(**values))


def last_successful_watermark(engine: Engine, pipeline_name: str) -> datetime | None:
    with engine.connect() as connection:
        return connection.execute(
            select(RUNS.c.source_watermark)
            .where(RUNS.c.pipeline_name == pipeline_name, RUNS.c.status == "completed")
            .order_by(RUNS.c.started_at.desc())
            .limit(1)
        ).scalar_one_or_none()


def _iso(moment: datetime | None) -> str | None:
    if moment is None:
        return None
    if moment.tzinfo is None:  # SQLite devuelve datetimes sin zona: se guardaron en UTC
        moment = moment.replace(tzinfo=config.utc_now().tzinfo)
    return moment.isoformat(timespec="seconds").replace("+00:00", "Z")


def _serialize(row) -> dict[str, Any]:
    run = dict(row._mapping)
    run["run_id"] = str(run["run_id"])
    for column in ("started_at", "finished_at", "source_watermark"):
        run[column] = _iso(run[column])
    return run


def get_latest_run(engine: Engine, pipeline_name: str = config.PIPELINE_NAME) -> dict[str, Any] | None:
    """La última corrida (por `started_at`) y el id de la última correcta; None si nunca corrió."""
    with engine.connect() as connection:
        latest = connection.execute(
            select(RUNS).where(RUNS.c.pipeline_name == pipeline_name).order_by(RUNS.c.started_at.desc()).limit(1)
        ).first()
        if latest is None:
            return None
        successful = connection.execute(
            select(RUNS.c.run_id)
            .where(RUNS.c.pipeline_name == pipeline_name, RUNS.c.status == "completed")
            .order_by(RUNS.c.started_at.desc())
            .limit(1)
        ).scalar_one_or_none()
    return {
        "pipeline_name": pipeline_name,
        "latest_run": _serialize(latest),
        "latest_successful_run_id": str(successful) if successful else None,
    }


def is_running(engine: Engine, pipeline_name: str = config.PIPELINE_NAME) -> bool:
    with engine.connect() as connection:
        return connection.execute(
            select(RUNS.c.run_id).where(RUNS.c.pipeline_name == pipeline_name, RUNS.c.status == "running").limit(1)
        ).first() is not None
