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
"""

import hashlib
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd
from prefect import flow, get_run_logger, task
from prefect.states import State
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from data.pipelines.weekly_warehouse_client_performance import (
    config, connections, extract, load, quality, transform,
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
    include_late_arrivals: bool = True,
) -> list[date]:
    """Semanas (lunes) a recalcular: la recién cerrada, `lookback_weeks` anteriores y las tardías."""
    return extract.resolve_weeks(
        connections.reader_engine(),
        as_of=as_of,
        extracted_until=extracted_until,
        environment=environment,
        week_start=week_start,
        lookback_weeks=lookback_weeks,
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
    """DataFrame semanal → reporting.weekly_warehouse_client_performance (UPSERT)."""
    engine = connections.writer_engine()
    ensure_reporting_schema(engine)
    return load.load_weekly_performance(engine, weekly, weeks, computed_at)


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


@flow(name=config.FLOW_NAME)
def weekly_warehouse_client_performance_flow(
    week_start: date | None = None,
    lookback_weeks: int = config.DEFAULT_LOOKBACK_WEEKS,
    environment: str | None = None,
    as_of: datetime | None = None,
) -> dict:
    """Recalcula las semanas pendientes y las carga. Devuelve el resumen de la corrida.

    - `week_start`: lunes de la semana a calcular; por defecto, la última semana ISO cerrada.
    - `lookback_weeks`: semanas anteriores que se recalculan también (red de seguridad).
    - `environment`: `tags.environment` de los eventos a leer; por defecto el de la API.
    - `as_of`: «ahora» de la corrida (para reproducir una corrida pasada); por defecto, now UTC.
    """
    logger = get_run_logger()
    now = as_of or config.utc_now()
    extracted_until = now
    environment = environment or connections.default_environment()

    # Críticas: `return_state=True` en lugar de dejar que la excepción se propague sola, para
    # saber en qué etapa falló y detener la corrida con ese dato (`_require`).
    weeks = _require(resolve_weeks_to_process(now, extracted_until, environment, week_start, lookback_weeks,
                                              return_state=True), "extract")
    events = _require(extract_inventory_events(weeks, extracted_until, environment, return_state=True), "extract")
    result = _require(transform_weekly_performance(events, weeks, return_state=True), "transform")
    loaded = _require(load_weekly_performance(result.weekly, weeks, now, return_state=True), "load")

    # Opcionales: un fallo se registra como aviso y la corrida termina Completed.
    warnings: list[dict] = []
    mismatches = _optional(check_outbound_reconciliation(result.weekly, weeks, return_state=True),
                           "check_outbound_reconciliation", warnings)
    if mismatches:
        warnings.append({"step": "check_outbound_reconciliation", "mismatches": mismatches})
    _optional(export_weekly_snapshot(result.weekly, weeks, now, return_state=True), "export_weekly_snapshot", warnings)

    summary = {
        "weeks_processed": [week.isoformat() for week in weeks],
        "events_extracted": result.events_in,
        "events_discarded": result.events_discarded,
        "events_deduplicated": result.events_deduplicated,
        "rows_upserted": loaded.rows_upserted,
        "rows_deleted": loaded.rows_deleted,
        "warnings": warnings,
    }
    logger.info("weekly_warehouse_client_performance %s", summary)
    return summary
