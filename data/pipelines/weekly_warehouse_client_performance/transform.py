"""Etapa 2 — Transformación (PIPELINE_DESIGN.md §5.1). Pura: sin base de datos, sin `now()`, sin bucles.

Una función por paso, para que cada KPI se calcule (y se pruebe) por separado. El subflow
`compute_weekly_warehouse_client_kpis` de pipeline.py envuelve cada una en su propia task:

    prepare_inventory_events ─┬─► inbound_volume          Volumen de entrada
                              ├─► outbound_throughput ──┐ Throughput de salida
                              ├─► stockout_frequency     │ Frecuencia de quiebre de stock
                              └─► discrepancy_rate ◄─────┘ Tasa de discrepancia
                                        └──► assemble_weekly_performance

1. `prepare_inventory_events`: valida (fuera `warehouse` desconocido, `client_id` vacío,
   `quantity` no numérica o negativa, `timestamp` ilegible; se cuentan en `events_discarded`),
   convierte tipos (`week_start` = lunes UTC de la semana ISO), se queda con las semanas pedidas
   y deduplica por `(event_type, warehouse, business_key)`.
2. Un cálculo por KPI, agrupando por `warehouse × client_id × week_start` (una fila nunca mezcla
   clientes: `client_id` es parte de la clave).
3. `assemble_weekly_performance`: une los cuatro en la forma de la tabla del BRIEFING.

Definición de cada KPI (BRIEFING §2 y §4):

    inbound_units_count       suma de `quantity` de inbound_order_created        Volumen de entrada
    outbound_orders_count     conteo de outbound_order_created                   Throughput de salida
    stockout_events_count     conteo de stock_threshold_triggered                Frecuencia de quiebre de stock
    discrepancy_events_count  conteo de inventory_discrepancy_detected           (apoyo)
    discrepancy_rate          discrepancy_events_count / outbound_orders_count   Tasa de discrepancia
                              (0 si no hubo pedidos de salida esa semana)
"""

from datetime import date
from typing import NamedTuple

import pandas as pd

from . import config

# Si cambia la lógica, se sube la versión: invalida la caché de Prefect de las tasks de transformación.
TRANSFORM_VERSION = "2"

KEYS = list(config.KEY_COLUMNS)
WEEKLY_COLUMNS = [*config.KEY_COLUMNS, *config.KPI_COLUMNS]
RAW_EVENT_COLUMNS = ("event_type", "timestamp", "warehouse", "client_id", "quantity", "business_key")
PREPARED_COLUMNS = ("event_type", "timestamp", "warehouse", "client_id", "quantity", "week_start")
_COUNT_COLUMNS = list(config.KPI_COLUMNS[:-1])


class PreparedEvents(NamedTuple):
    events: pd.DataFrame       # eventos válidos, deduplicados, con `week_start`
    events_in: int             # filas recibidas de la extracción
    events_discarded: int      # descartadas por validación
    events_deduplicated: int   # eliminadas por clave de negocio repetida


class WeeklyPerformance(NamedTuple):
    weekly: pd.DataFrame       # una fila por warehouse × client_id × week_start (WEEKLY_COLUMNS)
    events_in: int
    events_discarded: int
    events_deduplicated: int


def empty_weekly() -> pd.DataFrame:
    return pd.DataFrame(columns=WEEKLY_COLUMNS)


def _require_columns(frame: pd.DataFrame, columns, step: str) -> None:
    """Entrada defensiva: un DataFrame sin las columnas esperadas es un error de programación o de
    la extracción, no un dato a descartar; se falla con un mensaje que dice qué falta."""
    if not isinstance(frame, pd.DataFrame):
        raise TypeError(f"{step}: se esperaba un DataFrame, llegó {type(frame).__name__}")
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise ValueError(f"{step}: faltan las columnas {missing}")


# =========================================================
# 1. PREPARAR
# =========================================================


def prepare_inventory_events(events: pd.DataFrame, weeks: list[date]) -> PreparedEvents:
    _require_columns(events, RAW_EVENT_COLUMNS, "prepare_inventory_events")
    events_in = len(events)
    df = events.copy()

    # Validar: un evento malformado se descarta (y se cuenta), no tumba la corrida.
    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce")
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, format="ISO8601", errors="coerce")
    client = df["client_id"].astype("string").str.strip()
    valid = (
        df["warehouse"].isin(config.WAREHOUSES)
        & client.notna() & (client != "")
        & df["quantity"].notna() & (df["quantity"] >= 0)
        & df["timestamp"].notna()
        & df["event_type"].isin(config.SOURCE_EVENT_TYPES)
    ).fillna(False).astype(bool)
    discarded = int((~valid).sum())
    df = df[valid].copy()
    df["client_id"] = client[valid].astype(str)

    # Convertir tipos ANTES de agrupar: agrupar textos que parecen fechas da grupos falsos.
    df["week_start"] = (df["timestamp"] - pd.to_timedelta(df["timestamp"].dt.day_of_week, unit="D")).dt.normalize().dt.date
    df = df[df["week_start"].isin(set(weeks))]

    # Deduplicar por movimiento (se conserva el más antiguo). Sin id de dominio no se deduplica.
    df = df.sort_values("timestamp", kind="stable")
    has_key = df["business_key"].notna()
    keyed = df[has_key].drop_duplicates(subset=["event_type", "warehouse", "business_key"], keep="first")
    deduplicated = int(has_key.sum() - len(keyed))
    df = pd.concat([keyed, df[~has_key]])

    return PreparedEvents(df[list(PREPARED_COLUMNS)].reset_index(drop=True), events_in, discarded, deduplicated)


# =========================================================
# 2. UN CÁLCULO POR KPI
# =========================================================


def _count_by_key(events: pd.DataFrame, event_type: str, column: str) -> pd.DataFrame:
    selected = events[events["event_type"] == event_type]
    counts = selected.groupby(KEYS, as_index=False).size().rename(columns={"size": column})
    counts[column] = counts[column].astype(int)
    return counts[[*KEYS, column]]


def inbound_volume(events: pd.DataFrame) -> pd.DataFrame:
    """Volumen de entrada: unidades recibidas = **suma** de `quantity` de inbound_order_created."""
    _require_columns(events, PREPARED_COLUMNS, "inbound_volume")
    inbound = events[events["event_type"] == config.INBOUND_EVENT]
    volume = inbound.groupby(KEYS, as_index=False)["quantity"].sum().rename(columns={"quantity": "inbound_units_count"})
    volume["inbound_units_count"] = volume["inbound_units_count"].astype(int)
    return volume[[*KEYS, "inbound_units_count"]]


def outbound_throughput(events: pd.DataFrame) -> pd.DataFrame:
    """Throughput de salida: pedidos despachados = **conteo** de outbound_order_created."""
    _require_columns(events, PREPARED_COLUMNS, "outbound_throughput")
    return _count_by_key(events, config.OUTBOUND_EVENT, "outbound_orders_count")


def stockout_frequency(events: pd.DataFrame) -> pd.DataFrame:
    """Frecuencia de quiebre de stock: conteo de stock_threshold_triggered."""
    _require_columns(events, PREPARED_COLUMNS, "stockout_frequency")
    return _count_by_key(events, config.STOCKOUT_EVENT, "stockout_events_count")


def discrepancy_rate(events: pd.DataFrame, outbound: pd.DataFrame) -> pd.DataFrame:
    """Tasa de discrepancia = discrepancias / pedidos de salida de la misma combinación y semana;
    0 si no hubo pedidos de salida (BRIEFING §4). Devuelve también el conteo de apoyo."""
    _require_columns(events, PREPARED_COLUMNS, "discrepancy_rate")
    _require_columns(outbound, [*KEYS, "outbound_orders_count"], "discrepancy_rate")
    discrepancies = _count_by_key(events, config.DISCREPANCY_EVENT, "discrepancy_events_count")
    merged = discrepancies.merge(outbound, on=KEYS, how="outer")
    merged[["discrepancy_events_count", "outbound_orders_count"]] = (
        merged[["discrepancy_events_count", "outbound_orders_count"]].fillna(0).astype(int)
    )
    denominator = merged["outbound_orders_count"]
    rate = (merged["discrepancy_events_count"] / denominator.where(denominator > 0)).fillna(0.0)
    merged["discrepancy_rate"] = rate.round(config.DISCREPANCY_RATE_DECIMALS).astype(float)
    return merged[[*KEYS, "discrepancy_events_count", "discrepancy_rate"]]


# =========================================================
# 3. ENSAMBLAR
# =========================================================


def assemble_weekly_performance(
    inbound: pd.DataFrame, outbound: pd.DataFrame, stockouts: pd.DataFrame, discrepancies: pd.DataFrame
) -> pd.DataFrame:
    """Los cuatro KPIs en una fila por warehouse × client_id × week_start (forma de la tabla del BRIEFING)."""
    parts = [inbound, outbound, stockouts, discrepancies]
    weekly = parts[0].merge(parts[1], on=KEYS, how="outer").merge(parts[2], on=KEYS, how="outer").merge(parts[3], on=KEYS, how="outer")
    weekly[_COUNT_COLUMNS] = weekly.reindex(columns=_COUNT_COLUMNS).fillna(0).astype(int)
    weekly["discrepancy_rate"] = weekly.reindex(columns=["discrepancy_rate"])["discrepancy_rate"].fillna(0.0).astype(float)
    if weekly.empty:
        return empty_weekly()
    return weekly.sort_values(["week_start", "warehouse", "client_id"]).reset_index(drop=True)[WEEKLY_COLUMNS]


def transform_weekly_performance(events: pd.DataFrame, weeks: list[date]) -> WeeklyPerformance:
    """Toda la transformación de una vez (los mismos pasos que el subflow, sin Prefect)."""
    prepared = prepare_inventory_events(events, weeks)
    outbound = outbound_throughput(prepared.events)
    weekly = assemble_weekly_performance(
        inbound_volume(prepared.events), outbound, stockout_frequency(prepared.events),
        discrepancy_rate(prepared.events, outbound),
    )
    return WeeklyPerformance(weekly, prepared.events_in, prepared.events_discarded, prepared.events_deduplicated)
