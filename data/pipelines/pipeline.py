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
"""

from datetime import date, datetime

import pandas as pd
from prefect import flow, get_run_logger, task

from data.pipelines.weekly_warehouse_client_performance import (
    config, connections, extract, load, quality, transform,
)
from data.pipelines.weekly_warehouse_client_performance.load import LoadResult
from data.pipelines.weekly_warehouse_client_performance.schema import ensure_reporting_schema
from data.pipelines.weekly_warehouse_client_performance.transform import WeeklyPerformance


# =========================================================
# TASKS CRÍTICAS: extracción → transformación → carga
# =========================================================


@task(name="resolve_weeks_to_process")
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


@task(name="extract_inventory_events")
def extract_inventory_events(weeks: list[date], extracted_until: datetime, environment: str) -> pd.DataFrame:
    """telemetry_events (solo lectura) → DataFrame con una fila por evento de origen."""
    return extract.extract_inventory_events(connections.reader_engine(), weeks, extracted_until, environment)


@task(name="transform_weekly_performance")
def transform_weekly_performance(events: pd.DataFrame, weeks: list[date]) -> WeeklyPerformance:
    """DataFrame de eventos → una fila por warehouse × client_id × week_start con los cuatro KPIs."""
    return transform.transform_weekly_performance(events, weeks)


@task(name="load_weekly_performance")
def load_weekly_performance(weekly: pd.DataFrame, weeks: list[date], computed_at: datetime) -> LoadResult:
    """DataFrame semanal → reporting.weekly_warehouse_client_performance (UPSERT)."""
    engine = connections.writer_engine()
    ensure_reporting_schema(engine)
    return load.load_weekly_performance(engine, weekly, weeks, computed_at)


# =========================================================
# TASKS OPCIONALES: su fallo no detiene la corrida
# =========================================================


@task(name="check_outbound_reconciliation")
def check_outbound_reconciliation(weekly: pd.DataFrame, weeks: list[date]) -> list[dict]:
    """Aviso de calidad: outbound_orders_count frente a las salidas `dispatch` de stock_exit."""
    return quality.check_outbound_reconciliation(connections.reader_engine(), weekly, weeks)


@task(name="export_weekly_snapshot")
def export_weekly_snapshot(weekly: pd.DataFrame, weeks: list[date], computed_at: datetime) -> list[str]:
    """Copia JSON de cada semana cargada (data/process/reporting/…)."""
    return quality.export_weekly_snapshot(weekly, weeks, computed_at)


# =========================================================
# FLOW PRINCIPAL
# =========================================================


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

    weeks = resolve_weeks_to_process(now, extracted_until, environment, week_start, lookback_weeks)
    events = extract_inventory_events(weeks, extracted_until, environment)
    result = transform_weekly_performance(events, weeks)
    loaded = load_weekly_performance(result.weekly, weeks, now)

    # Pasos opcionales: `return_state=True` devuelve el State en vez de lanzar la excepción, así
    # que un fallo aquí se registra como aviso y la corrida termina Completed.
    warnings: list[dict] = []
    reconciliation = check_outbound_reconciliation(result.weekly, weeks, return_state=True)
    if reconciliation.is_failed():
        warnings.append({"step": "check_outbound_reconciliation", "error": str(reconciliation.message)})
    elif mismatches := reconciliation.result():
        warnings.append({"step": "check_outbound_reconciliation", "mismatches": mismatches})
    snapshot = export_weekly_snapshot(result.weekly, weeks, now, return_state=True)
    if snapshot.is_failed():
        warnings.append({"step": "export_weekly_snapshot", "error": str(snapshot.message)})

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
