"""Pipeline de desempeño de negocio de TrackFlow, orquestado con Prefect (PIPELINE_DESIGN.md §10).

Flow principal `weekly-warehouse-client-performance`: produce
`reporting.weekly_warehouse_client_performance`, el consolidado del «Reporte Semanal de
Desempeño por Almacén y Cliente» de Thomas (CEO) y Ana (Head of Warehouse Operations).

    resolve_weeks_to_process ─► extract_inventory_events ─► transform_weekly_performance ─► load_weekly_performance
                                                                                               │
                                       (opcionales, no críticos) check_outbound_reconciliation ┤
                                                                 export_weekly_snapshot ────────┘

Cada task envuelve una función pura de `weekly_warehouse_client_performance/` (que se prueba sin
Prefect) y declara sus entradas y salidas. Lee `telemetry_events` en solo lectura y solo escribe
en el esquema `reporting`.

Resiliencia:
- Reintentos en las tasks que hablan con Supabase, solo ante errores transitorios de conexión
  (`retry_condition_fn`); un error de datos o de parámetros falla a la primera.
- Las tasks críticas se invocan con `return_state=True` y el flow decide qué hacer con un fallo
  (`_require`): lo registra con su etapa y detiene la corrida. Las opcionales registran el fallo
  como aviso y la corrida sigue.
- La transformación se cachea una hora por el contenido de su entrada.

Ejecución (frecuencia prevista: semanal, lunes 06:00 UTC; ver PIPELINE_DESIGN.md §15):

    python data/pipelines/pipeline.py                         # última semana cerrada + 1 de lookback
    python data/pipelines/pipeline.py --week-start 2026-11-02 # una semana concreta
    python data/pipelines/pipeline.py --backfill-from 2026-09-07 --backfill-to 2026-11-02
    python data/pipelines/pipeline.py --serve                 # deployment weekly-monday (cron 0 6 * * 1 UTC)

(`uv run python …` si el entorno virtual no está activado.)
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

# Ejecutado como script (`python data/pipelines/pipeline.py`), Python solo añade
# data/pipelines/ al path: se añade la raíz del repo para importar `data.*` y `services.*`.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pandas as pd  # noqa: E402
from prefect import flow, get_run_logger, task
from prefect.runtime import flow_run as current_flow_run
from prefect.states import State
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from data.pipelines.weekly_warehouse_client_performance import (
    config, connections, extract, load, quality, run_log, transform,
)
from data.pipelines.weekly_warehouse_client_performance.load import LoadResult
from data.pipelines.weekly_warehouse_client_performance.schema import ensure_reporting_schema
from data.pipelines.weekly_warehouse_client_performance.transform import WeeklyPerformance


# =========================================================
# REINTENTOS Y CACHÉ
# =========================================================

# Errores que merecen reintento: la conexión con Supabase se cayó, el pooler está saturado o la
# red tardó demasiado. Un `ValueError` (semana que no es lunes) o un error de programación
# fallarían igual en cada intento: reintentarlos solo retrasaría el aviso.
TRANSIENT_ERRORS = (OperationalError, PoolTimeoutError, ConnectionError, TimeoutError)


def _is_transient(exception: BaseException) -> bool:
    if isinstance(exception, DBAPIError) and exception.connection_invalidated:
        return True
    return isinstance(exception, TRANSIENT_ERRORS)


def retry_on_transient_errors(task, task_run, state: State) -> bool:
    """`retry_condition_fn` de Prefect: reintentar solo si el fallo es transitorio."""
    try:
        state.result()
    except Exception as exception:  # noqa: BLE001 - el State guarda la excepción de la task
        return _is_transient(exception)
    return False


def transform_cache_key(context, parameters: dict[str, Any]) -> str:
    """Clave de caché de `transform_weekly_performance`.

    La define **el contenido de la entrada**, no la hora ni el nombre de la corrida:
    - un hash SHA-256 de todas las filas del DataFrame de eventos (cada evento, con su `event_id`,
      tipo, timestamp, almacén, cliente, cantidad y clave de negocio),
    - las semanas pedidas,
    - `TRANSFORM_VERSION` (cambiar la lógica invalida todo lo cacheado).

    Mismos eventos y mismas semanas ⇒ mismo resultado (la transformación es pura), así que es
    seguro reutilizarlo. Si llega un solo evento tardío, el hash cambia y se recalcula.
    """
    events: pd.DataFrame = parameters["events"]
    digest = hashlib.sha256()
    digest.update(pd.util.hash_pandas_object(events.astype(str), index=False).to_numpy().tobytes())
    digest.update(",".join(week.isoformat() for week in parameters["weeks"]).encode())
    return f"{config.PIPELINE_NAME}-transform-v{transform.TRANSFORM_VERSION}-{digest.hexdigest()}"


# Válida una hora: es el margen del ticket («si ya corrió en la última hora, no repetir»). Cubre
# el caso típico —un disparo manual poco después de la corrida programada, o un reintento del
# flow tras un fallo en la carga— sin guardar resultados indefinidamente.
TRANSFORM_CACHE_EXPIRATION = timedelta(hours=1)


class PipelineStageError(RuntimeError):
    """Una etapa crítica falló: la corrida se detiene y se registra en qué etapa."""

    def __init__(self, stage: str, message: str):
        super().__init__(f"{stage}: {message}")
        self.stage = stage
        self.message = message


# =========================================================
# TASKS CRÍTICAS: extracción → transformación → carga
# =========================================================


# 3 reintentos con espera creciente (10 s, 1 min, 5 min): absorben un corte breve de la red o un
# reinicio del pooler de Supabase (~6 min en total) sin pasar de la ventana del lunes por la
# mañana. Es una lectura: repetirla no tiene efectos.
@task(name="resolve_weeks_to_process", retries=3, retry_delay_seconds=[10, 60, 300],
      retry_condition_fn=retry_on_transient_errors)
def resolve_weeks_to_process(
    as_of: datetime,
    extracted_until: datetime,
    environment: str,
    week_start: date | None,
    lookback_weeks: int,
    last_watermark: datetime | None,
    include_late_arrivals: bool = True,
) -> list[date]:
    """Semanas (lunes) a recalcular: la recién cerrada, `lookback_weeks` anteriores y las que
    tienen eventos ingeridos después de `last_watermark` (llegadas tardías)."""
    return extract.resolve_weeks(
        connections.reader_engine(),
        as_of=as_of,
        extracted_until=extracted_until,
        environment=environment,
        week_start=week_start,
        lookback_weeks=lookback_weeks,
        last_watermark=last_watermark,
        include_late_arrivals=include_late_arrivals,
    )


# Mismo criterio que resolve_weeks_to_process: 3 reintentos (10 s, 1 min, 5 min) para fallos
# transitorios de Supabase. Lectura con corte fijo (`extracted_until`): cada intento devuelve
# exactamente las mismas filas.
@task(name="extract_inventory_events", retries=3, retry_delay_seconds=[10, 60, 300],
      retry_condition_fn=retry_on_transient_errors, timeout_seconds=300)
def extract_inventory_events(weeks: list[date], extracted_until: datetime, environment: str) -> pd.DataFrame:
    """telemetry_events (solo lectura) → DataFrame con una fila por evento de origen."""
    return extract.extract_inventory_events(connections.reader_engine(), weeks, extracted_until, environment)


# Sin reintentos: no toca servicios externos y es determinista; si falla una vez, falla siempre.
# Con caché: ver transform_cache_key.
@task(name="transform_weekly_performance", cache_key_fn=transform_cache_key,
      cache_expiration=TRANSFORM_CACHE_EXPIRATION, persist_result=True)
def transform_weekly_performance(events: pd.DataFrame, weeks: list[date]) -> WeeklyPerformance:
    """DataFrame de eventos → una fila por warehouse × client_id × week_start con los cuatro KPIs."""
    return transform.transform_weekly_performance(events, weeks)


# 2 reintentos cada 30 s: la carga es una única transacción idempotente (UPSERT por la clave
# natural), así que repetirla tras un corte nunca duplica ni corrompe. Son menos que en la
# lectura porque cada intento escribe: si la base sigue caída al minuto, mejor fallar y avisar.
# Sin caché a propósito: el destino es estado externo y la carga debe ejecutarse siempre.
@task(name="load_weekly_performance", retries=2, retry_delay_seconds=30,
      retry_condition_fn=retry_on_transient_errors, timeout_seconds=300)
def load_weekly_performance(weekly: pd.DataFrame, weeks: list[date], computed_at: datetime) -> LoadResult:
    """DataFrame semanal → reporting.weekly_warehouse_client_performance (una transacción idempotente)."""
    return load.load_weekly_performance(connections.writer_engine(), weekly, weeks, computed_at)


# =========================================================
# TASKS DE CONTROL: log de ejecución (reporting.pipeline_runs)
# =========================================================


# 2 reintentos a los 10 s: es la primera escritura de la corrida en Supabase; si la base tarda en
# responder unos segundos, mejor esperar que perder la corrida del lunes. Una corrida ya en curso
# (PipelineAlreadyRunning) no es transitoria: no se reintenta.
@task(name="start_pipeline_run", retries=2, retry_delay_seconds=10, retry_condition_fn=retry_on_transient_errors)
def start_pipeline_run(
    run_id: uuid.UUID,
    trigger: str,
    triggered_by: str | None,
    started_at: datetime,
    source_watermark: datetime,
    parameters: dict[str, Any],
) -> datetime | None:
    """Crea el esquema si falta, registra la corrida como `running` y devuelve la marca de agua
    de la última corrida correcta (None si es la primera)."""
    engine = connections.writer_engine()
    ensure_reporting_schema(engine)
    last_watermark = run_log.last_successful_watermark(engine, config.PIPELINE_NAME)
    run_log.start_run(
        engine, run_id=run_id, pipeline_name=config.PIPELINE_NAME, trigger=trigger, triggered_by=triggered_by,
        started_at=started_at, source_watermark=source_watermark, parameters=parameters,
        code_version=code_version(),
    )
    return last_watermark


# Mismo criterio que start_pipeline_run. Si aun así falla, los datos ya están cargados (y son
# correctos); la corrida queda `failed` y la siguiente recalcula y escribe lo mismo.
@task(name="finish_pipeline_run", retries=2, retry_delay_seconds=10, retry_condition_fn=retry_on_transient_errors)
def finish_pipeline_run(run_id: uuid.UUID, summary: dict[str, Any]) -> None:
    """Cierra la corrida como `completed` con sus contadores y avisos."""
    run_log.finish_run(
        connections.writer_engine(), run_id, finished_at=config.utc_now(),
        weeks_processed=summary["weeks_processed"], counters=summary, warnings=summary["warnings"],
    )


# =========================================================
# TASKS OPCIONALES: su fallo no detiene la corrida
# =========================================================


# 1 reintento a los 10 s: lee stock_exit en Supabase, pero es un aviso de calidad; no merece
# retrasar el cierre de la corrida más de unos segundos.
@task(name="check_outbound_reconciliation", retries=1, retry_delay_seconds=10,
      retry_condition_fn=retry_on_transient_errors)
def check_outbound_reconciliation(weekly: pd.DataFrame, weeks: list[date]) -> list[dict]:
    """Aviso de calidad: outbound_orders_count frente a las salidas `dispatch` de stock_exit."""
    return quality.check_outbound_reconciliation(connections.reader_engine(), weekly, weeks)


# Sin reintentos: escribe en disco local, no en un servicio externo.
@task(name="export_weekly_snapshot")
def export_weekly_snapshot(weekly: pd.DataFrame, weeks: list[date], computed_at: datetime) -> list[str]:
    """Copia JSON de cada semana cargada (data/process/reporting/…)."""
    return quality.export_weekly_snapshot(weekly, weeks, computed_at)


# =========================================================
# FLOW PRINCIPAL
# =========================================================


def _require(state: State, stage: str):
    """Resultado de una task crítica; si falló, detiene la corrida con su etapa."""
    if state.is_failed() or state.is_crashed() or state.is_cancelled():
        try:
            state.result()
        except Exception as exception:  # noqa: BLE001
            raise PipelineStageError(stage, f"{type(exception).__name__}: {exception}") from exception
        raise PipelineStageError(stage, str(state.message))
    return state.result()


def _optional(state: State, step: str, warnings: list[dict]) -> Any:
    """Resultado de una task opcional; si falló, se anota como aviso y se devuelve None."""
    if state.is_failed() or state.is_crashed():
        get_run_logger().warning("optional step %s failed: %s", step, state.message)
        warnings.append({"step": step, "error": str(state.message)})
        return None
    return state.result()


def code_version() -> str | None:
    """SHA de git desplegado (CODE_VERSION en contenedores, `git rev-parse` en local)."""
    if version := os.getenv("CODE_VERSION", "").strip():
        return version
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, timeout=5, check=True,
        ).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def _current_run_id() -> uuid.UUID:
    """El id del flow run de Prefect: enlaza reporting.pipeline_runs con la UI de Prefect."""
    return uuid.UUID(str(current_flow_run.id)) if current_flow_run.id else uuid.uuid4()


def _record_failure(run_id: uuid.UUID, stage: str, message: str, summary: dict[str, Any] | None = None) -> None:
    """Marca la corrida como `failed`. Si la base tampoco responde, la siguiente corrida la marcará
    como `crashed` (corrida colgada); el fallo queda igualmente en el estado de Prefect."""
    try:
        run_log.fail_run(
            connections.writer_engine(), run_id, finished_at=config.utc_now(), error_stage=stage,
            error_message=message, weeks_processed=(summary or {}).get("weeks_processed"),
            counters=summary, warnings=(summary or {}).get("warnings"),
        )
    except Exception as error:  # noqa: BLE001
        get_run_logger().error("no se pudo registrar el fallo de la corrida %s: %s", run_id, error)


def _mark_crashed(flow, flow_run, state) -> None:
    """Hook `on_crashed`: el proceso murió (OOM, worker reiniciado) a mitad de la corrida."""
    try:
        run_log.fail_run(connections.writer_engine(), uuid.UUID(str(flow_run.id)), finished_at=config.utc_now(),
                         error_stage="crashed", error_message=str(state.message))
    except Exception:  # noqa: BLE001 - lo recogerá mark_stale_runs en la siguiente corrida
        pass


@flow(name=config.FLOW_NAME, on_crashed=[_mark_crashed])
def weekly_warehouse_client_performance_flow(
    week_start: date | None = None,
    lookback_weeks: int = config.DEFAULT_LOOKBACK_WEEKS,
    environment: str | None = None,
    trigger: Literal["scheduled", "manual", "backfill"] = "scheduled",
    triggered_by: str | None = None,
    as_of: datetime | None = None,
    include_late_arrivals: bool = True,
) -> dict:
    """Recalcula las semanas pendientes, las carga y registra la corrida. Devuelve su resumen.

    - `week_start`: lunes de la semana a calcular; por defecto, la última semana ISO cerrada.
    - `lookback_weeks`: semanas anteriores que se recalculan también (red de seguridad).
    - `environment`: `tags.environment` de los eventos a leer; por defecto el de la API.
    - `trigger` / `triggered_by`: quién la lanzó (deployment, POST /reporting/pipeline-runs, backfill).
    - `as_of`: «ahora» de la corrida (para reproducir una corrida pasada); por defecto, now UTC.
    """
    logger = get_run_logger()
    run_id = _current_run_id()
    now = as_of or config.utc_now()
    extracted_until = now  # corte fijo: lo ingerido después entra en la siguiente corrida
    environment = environment or connections.default_environment()
    parameters = {
        "week_start": week_start.isoformat() if week_start else None,
        "lookback_weeks": lookback_weeks,
        "environment": environment,
        "include_late_arrivals": include_late_arrivals,
    }

    # Si no se puede registrar el inicio (otra corrida en curso, base caída), no se hace nada más.
    last_watermark = _require(start_pipeline_run(run_id, trigger, triggered_by, config.utc_now(), extracted_until,
                                                 parameters, return_state=True), "start")

    summary: dict[str, Any] = {"run_id": str(run_id), "weeks_processed": [], "warnings": []}
    try:
        # Críticas: `return_state=True` en lugar de dejar que la excepción se propague sola, para
        # registrar en qué etapa falló y detener la corrida con ese dato (`_require`).
        weeks = _require(resolve_weeks_to_process(now, extracted_until, environment, week_start, lookback_weeks,
                                                  last_watermark, include_late_arrivals, return_state=True), "extract")
        summary["weeks_processed"] = [week.isoformat() for week in weeks]
        events = _require(extract_inventory_events(weeks, extracted_until, environment, return_state=True), "extract")
        summary["events_extracted"] = len(events)
        result = _require(transform_weekly_performance(events, weeks, return_state=True), "transform")
        summary.update(events_discarded=result.events_discarded, events_deduplicated=result.events_deduplicated)
        loaded = _require(load_weekly_performance(result.weekly, weeks, now, return_state=True), "load")
        summary.update(rows_upserted=loaded.rows_upserted, rows_deleted=loaded.rows_deleted)
    except PipelineStageError as error:
        _record_failure(run_id, error.stage, error.message, summary)
        raise

    # Opcionales: un fallo se registra como aviso y la corrida termina Completed.
    warnings: list[dict] = summary["warnings"]
    mismatches = _optional(check_outbound_reconciliation(result.weekly, weeks, return_state=True),
                           "check_outbound_reconciliation", warnings)
    if mismatches:
        warnings.append({"step": "check_outbound_reconciliation", "mismatches": mismatches})
    _optional(export_weekly_snapshot(result.weekly, weeks, now, return_state=True), "export_weekly_snapshot", warnings)

    finish = finish_pipeline_run(run_id, summary, return_state=True)
    if finish.is_failed():
        _record_failure(run_id, "load", f"no se pudo cerrar el log: {finish.message}", summary)
        _require(finish, "load")
    summary["status"] = "completed"
    logger.info("weekly_warehouse_client_performance %s", summary)
    return summary


# =========================================================
# FLOW DE BACKFILL (subflows, PIPELINE_DESIGN.md §10.2)
# =========================================================


@flow(name=config.BACKFILL_FLOW_NAME)
def backfill_weekly_warehouse_client_performance_flow(
    from_week: date,
    to_week: date,
    environment: str | None = None,
    triggered_by: str | None = None,
) -> list[dict]:
    """Recalcula cada semana de `[from_week, to_week]` como subflow propio, en orden.

    Cada semana es su propia transacción y su propia fila en reporting.pipeline_runs
    (`trigger = backfill`): si falla la semana 7 de 20, las 6 anteriores quedan cargadas y
    relanzar el backfill las rehace sin efecto.
    """
    if from_week.weekday() != 0 or to_week.weekday() != 0:
        raise ValueError("from_week y to_week deben ser lunes")
    if from_week > to_week:
        raise ValueError("from_week debe ser anterior o igual a to_week")
    weeks = pd.date_range(from_week, to_week, freq="7D").date
    return [
        weekly_warehouse_client_performance_flow(
            week_start=week, lookback_weeks=0, environment=environment, trigger="backfill",
            triggered_by=triggered_by, include_late_arrivals=False,
        )
        for week in weeks
    ]


# =========================================================
# CLI
# =========================================================


def _monday(value: str) -> date:
    day = date.fromisoformat(value)
    if day.weekday() != 0:
        raise argparse.ArgumentTypeError(f"{value} no es lunes")
    return day


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python data/pipelines/pipeline.py",
        description="Pipeline semanal de desempeño por almacén y cliente (reporting.weekly_warehouse_client_performance).",
    )
    parser.add_argument("--week-start", type=_monday, help="lunes de la semana (YYYY-MM-DD); por defecto, la última cerrada")
    parser.add_argument("--lookback-weeks", type=int, default=config.DEFAULT_LOOKBACK_WEEKS,
                        help=f"semanas anteriores a recalcular (0-{config.MAX_LOOKBACK_WEEKS}; por defecto 1)")
    parser.add_argument("--environment", help="tags.environment de los eventos (por defecto, el de la API)")
    parser.add_argument("--backfill-from", type=_monday, help="backfill: primer lunes")
    parser.add_argument("--backfill-to", type=_monday, help="backfill: último lunes")
    parser.add_argument("--serve", action="store_true",
                        help="sirve el deployment weekly-monday (cron 0 6 * * 1, UTC) y espera a sus corridas")
    args = parser.parse_args(argv)
    if (args.backfill_from is None) != (args.backfill_to is None):
        parser.error("--backfill-from y --backfill-to van juntos")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.serve:
        weekly_warehouse_client_performance_flow.serve(
            name=config.DEPLOYMENT_NAME.split("/")[1],
            cron=config.SCHEDULE_CRON,  # Prefect interpreta el cron en UTC
            parameters={"lookback_weeks": config.DEFAULT_LOOKBACK_WEEKS, "trigger": "scheduled"},
        )
        return 0
    try:
        if args.backfill_from:
            result: Any = backfill_weekly_warehouse_client_performance_flow(
                args.backfill_from, args.backfill_to, environment=args.environment,
            )
        else:
            result = weekly_warehouse_client_performance_flow(
                week_start=args.week_start, lookback_weeks=args.lookback_weeks,
                environment=args.environment, trigger="manual",
            )
    except PipelineStageError as error:
        # El detalle ya está en el log de Prefect y en reporting.pipeline_runs.
        print(f"pipeline failed at stage '{error.stage}': {error.message}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
