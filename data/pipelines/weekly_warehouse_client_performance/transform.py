"""Etapa 2 — Transformación (PIPELINE_DESIGN.md §5.1). Pura: sin base de datos, sin `now()`.

Mismos pasos que el pipeline técnico del hito 17 (refinar → convertir tipos → agrupar →
agregar), sin bucles:

1. Validar: fuera las filas con `warehouse` desconocido, `client_id` vacío o `quantity` no
   numérica o negativa (se cuentan en `events_discarded`).
2. Convertir tipos: `to_datetime(utc=True)` y `week_start` = lunes UTC de la semana ISO. Solo se
   quedan las semanas pedidas.
3. Deduplicar por `(event_type, warehouse, business_key)`: un mismo movimiento emitido con dos
   `eventId` cuenta una vez (`events_deduplicated`).
4. Agrupar por `warehouse × client_id × week_start` y agregar con `sum` (una fila nunca mezcla
   clientes: `client_id` es parte de la clave).
5. `discrepancy_rate = discrepancy_events_count / outbound_orders_count`, 0 si no hubo salidas.

Definición de cada KPI (BRIEFING §2 y §4):

    inbound_units_count       suma de `quantity` de inbound_order_created        Volumen de entrada
    outbound_orders_count     conteo de outbound_order_created                   Throughput de salida
    stockout_events_count     conteo de stock_threshold_triggered                Frecuencia de quiebre
    discrepancy_events_count  conteo de inventory_discrepancy_detected           (apoyo)
    discrepancy_rate          discrepancy_events_count / outbound_orders_count   Tasa de discrepancia
"""

from datetime import date
from typing import NamedTuple

import pandas as pd

from . import config

# Si cambia la lógica, se sube la versión: invalida la caché de Prefect de esta transformación.
TRANSFORM_VERSION = "1"

WEEKLY_COLUMNS = [*config.KEY_COLUMNS, *config.KPI_COLUMNS]
_COUNT_COLUMNS = list(config.KPI_COLUMNS[:-1])


class WeeklyPerformance(NamedTuple):
    weekly: pd.DataFrame       # una fila por warehouse × client_id × week_start (WEEKLY_COLUMNS)
    events_in: int             # filas recibidas de la extracción
    events_discarded: int      # descartadas por validación
    events_deduplicated: int   # eliminadas por clave de negocio repetida


def empty_weekly() -> pd.DataFrame:
    return pd.DataFrame(columns=WEEKLY_COLUMNS)


def transform_weekly_performance(events: pd.DataFrame, weeks: list[date]) -> WeeklyPerformance:
    events_in = len(events)
    if events.empty:
        return WeeklyPerformance(empty_weekly(), events_in, 0, 0)

    # 1. Validar.
    df = events.copy()
    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce")
    client = df["client_id"].astype("string").str.strip()
    valid = (
        df["warehouse"].isin(config.WAREHOUSES)
        & client.notna() & (client != "")
        & df["quantity"].notna() & (df["quantity"] >= 0)
        & df["event_type"].isin(config.SOURCE_EVENT_TYPES)
    )
    discarded = int((~valid).sum())
    df = df[valid].copy()
    df["client_id"] = client[valid]

    # 2. Convertir tipos ANTES de agrupar: agrupar textos que parecen fechas da grupos falsos.
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, format="ISO8601")
    df["week_start"] = (df["timestamp"] - pd.to_timedelta(df["timestamp"].dt.day_of_week, unit="D")).dt.normalize().dt.date
    df = df[df["week_start"].isin(set(weeks))]

    # 3. Deduplicar por movimiento (se conserva el más antiguo). Sin id de dominio no se deduplica.
    df = df.sort_values("timestamp", kind="stable")
    has_key = df["business_key"].notna()
    keyed = df[has_key].drop_duplicates(subset=["event_type", "warehouse", "business_key"], keep="first")
    deduplicated = int(has_key.sum() - len(keyed))
    df = pd.concat([keyed, df[~has_key]])

    if df.empty:
        return WeeklyPerformance(empty_weekly(), events_in, discarded, deduplicated)

    # 4. Agrupar y agregar: un indicador por KPI y un único groupby.
    df["inbound_units_count"] = df["quantity"].where(df["event_type"] == config.INBOUND_EVENT, 0)
    df["outbound_orders_count"] = (df["event_type"] == config.OUTBOUND_EVENT).astype(int)
    df["stockout_events_count"] = (df["event_type"] == config.STOCKOUT_EVENT).astype(int)
    df["discrepancy_events_count"] = (df["event_type"] == config.DISCREPANCY_EVENT).astype(int)
    weekly = df.groupby(list(config.KEY_COLUMNS), as_index=False)[_COUNT_COLUMNS].sum()
    weekly[_COUNT_COLUMNS] = weekly[_COUNT_COLUMNS].astype(int)

    # 5. Tasa de discrepancia (0 si no hubo pedidos de salida esa semana, BRIEFING §4).
    outbound = weekly["outbound_orders_count"]
    rate = (weekly["discrepancy_events_count"] / outbound.where(outbound > 0)).fillna(0.0)
    weekly["discrepancy_rate"] = rate.round(config.DISCREPANCY_RATE_DECIMALS).astype(float)

    weekly = weekly.sort_values(["week_start", "warehouse", "client_id"]).reset_index(drop=True)
    return WeeklyPerformance(weekly[WEEKLY_COLUMNS], events_in, discarded, deduplicated)
