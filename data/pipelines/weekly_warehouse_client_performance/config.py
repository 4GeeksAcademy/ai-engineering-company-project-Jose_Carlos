"""Constantes del pipeline: nombres, eventos de origen y valores de dominio (BRIEFING §3 y §4)."""

from datetime import date, datetime, timedelta, timezone

PIPELINE_NAME = "weekly_warehouse_client_performance"

# Nombres en Prefect (PIPELINE_DESIGN.md §10).
FLOW_NAME = "weekly-warehouse-client-performance"
BACKFILL_FLOW_NAME = "backfill-weekly-warehouse-client-performance"
# Subflows del flow principal (hito 20): uno por etapa, con el vocabulario del BRIEFING.
EXTRACT_FLOW_NAME = "extract-inventory-activity"
TRANSFORM_FLOW_NAME = "compute-weekly-warehouse-client-kpis"
LOAD_FLOW_NAME = "load-weekly-warehouse-client-performance"
RECONCILE_FLOW_NAME = "reconcile-outbound-throughput"
SNAPSHOT_FLOW_NAME = "export-weekly-performance-snapshot"
DEPLOYMENT_NAME = f"{FLOW_NAME}/weekly-monday"
SCHEDULE_CRON = "0 6 * * 1"  # lunes 06:00 UTC

# Los cuatro eventos de origen (métricas obligatorias de telemetría) y el KPI que alimentan.
INBOUND_EVENT = "inbound_order_created"            # Volumen de entrada
OUTBOUND_EVENT = "outbound_order_created"          # Throughput de salida; denominador de la tasa
STOCKOUT_EVENT = "stock_threshold_triggered"       # Frecuencia de quiebre de stock
DISCREPANCY_EVENT = "inventory_discrepancy_detected"  # numerador de la Tasa de discrepancia
SOURCE_EVENT_TYPES = (INBOUND_EVENT, OUTBOUND_EVENT, STOCKOUT_EVENT, DISCREPANCY_EVENT)

# Id de dominio que identifica el movimiento de cada evento (clave de deduplicación, §5.1).
BUSINESS_KEY_FIELDS = {
    INBOUND_EVENT: "inbound_order_id",
    OUTBOUND_EVENT: "outbound_order_id",
    STOCKOUT_EVENT: "trigger_order_id",
    DISCREPANCY_EVENT: "count_id",
}

WAREHOUSES = ("los_angeles", "zaragoza")

# Columnas del destino, en el orden del BRIEFING §5.
KPI_COLUMNS = (
    "inbound_units_count",
    "outbound_orders_count",
    "stockout_events_count",
    "discrepancy_events_count",
    "discrepancy_rate",
)
KEY_COLUMNS = ("warehouse", "client_id", "week_start")

DEFAULT_LOOKBACK_WEEKS = 1
MAX_LOOKBACK_WEEKS = 12
# Una corrida `running` más antigua que esto se considera muerta (Crashed) y se marca `failed`.
STALE_RUN_AFTER = timedelta(hours=1)
DISCREPANCY_RATE_DECIMALS = 4


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def week_monday(day: date) -> date:
    """Lunes de la semana ISO de `day`."""
    return day - timedelta(days=day.weekday())


def last_closed_week(now: datetime) -> date:
    """Lunes de la última semana ISO completa (UTC) antes de `now`."""
    return week_monday(now.astimezone(timezone.utc).date()) - timedelta(days=7)


def week_bounds(week_start: date) -> tuple[datetime, datetime]:
    """Ventana semiabierta `[lunes 00:00 UTC, lunes siguiente 00:00 UTC)`."""
    start = datetime(week_start.year, week_start.month, week_start.day, tzinfo=timezone.utc)
    return start, start + timedelta(days=7)
