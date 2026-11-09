"""Pasos OPCIONALES del pipeline (no críticos): su fallo se registra y la corrida sigue.

- `check_outbound_reconciliation()`: el control de calidad propuesto en PIPELINE_DESIGN.md §12.
  `outbound_order_created` lo emite el navegador, así que un despacho hecho por Swagger o una
  pestaña cerrada antes de enviar el lote no deja evento. Compara `outbound_orders_count` con las
  salidas `dispatch` de `stock_exit` de la misma semana y devuelve las diferencias como avisos.
  **No cambia ninguna cifra**: el reporte mide lo que captura la telemetría.
- `export_weekly_snapshot()`: copia JSON de cada semana cargada (mismo contrato que
  GET /reporting/weekly-warehouse-client-performance), para archivo o envío por correo. Un
  archivo por semana, sobrescrito en cada corrida: también es idempotente.
"""

import json
import os
from datetime import date, datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import select
from sqlalchemy.engine import Engine

from . import config

SNAPSHOT_ENV = "REPORTING_SNAPSHOT_DIR"
DEFAULT_SNAPSHOT_DIR = Path(__file__).resolve().parents[2] / "process" / "reporting" / config.PIPELINE_NAME


def check_outbound_reconciliation(engine: Engine, weekly: pd.DataFrame, weeks: list[date]) -> list[dict]:
    """Combinaciones cuya cifra de telemetría no cuadra con `stock_exit` (solo lectura)."""
    from services import telemetry
    from services.models import SKU, StockExit

    if not weeks:
        return []
    window_start, _ = config.week_bounds(min(weeks))
    _, window_end = config.week_bounds(max(weeks))
    statement = (
        select(StockExit.warehouse, SKU.client_name, StockExit.created_at)
        .join(SKU, SKU.id == StockExit.sku_id)
        .where(StockExit.exit_type == "dispatch", StockExit.created_at >= window_start, StockExit.created_at < window_end)
    )
    with engine.connect() as connection:
        exits = pd.DataFrame(connection.execute(statement).all(), columns=["warehouse", "client_name", "created_at"])

    keys = list(config.KEY_COLUMNS)
    if exits.empty:
        dispatches = pd.DataFrame(columns=[*keys, "stock_exit_dispatches"])
    else:
        exits["warehouse"] = exits["warehouse"].map(telemetry.WAREHOUSES)
        names = exits["client_name"].drop_duplicates()
        exits["client_id"] = exits["client_name"].map(dict(zip(names, names.map(telemetry.client_id))))
        moment = pd.to_datetime(exits["created_at"], utc=True, format="ISO8601")
        exits["week_start"] = (moment - pd.to_timedelta(moment.dt.day_of_week, unit="D")).dt.normalize().dt.date
        exits = exits[exits["week_start"].isin(set(weeks))]
        dispatches = exits.groupby(keys, as_index=False).size().rename(columns={"size": "stock_exit_dispatches"})

    telemetry_counts = weekly[[*keys, "outbound_orders_count"]].rename(
        columns={"outbound_orders_count": "telemetry_outbound_orders"}
    )
    merged = telemetry_counts.merge(dispatches, on=keys, how="outer")
    merged[["telemetry_outbound_orders", "stock_exit_dispatches"]] = (
        merged[["telemetry_outbound_orders", "stock_exit_dispatches"]].fillna(0).astype(int)
    )
    merged["difference"] = merged["telemetry_outbound_orders"] - merged["stock_exit_dispatches"]
    mismatches = merged[merged["difference"] != 0].sort_values(keys)
    mismatches["week_start"] = mismatches["week_start"].map(lambda day: day.isoformat())
    return mismatches.to_dict(orient="records")


def snapshot_payload(weekly: pd.DataFrame, week_start: date, computed_at: datetime) -> dict:
    rows = weekly[weekly["week_start"] == week_start].sort_values(["warehouse", "client_id"])
    entries = rows.drop(columns="week_start").to_dict(orient="records")
    return {
        "week_start": week_start.isoformat(),
        "computed_at": computed_at.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "entries": entries,
    }


def export_weekly_snapshot(
    weekly: pd.DataFrame, weeks: list[date], computed_at: datetime, directory: Path | None = None
) -> list[str]:
    """Escribe `week_start=YYYY-MM-DD.json` por cada semana procesada. Devuelve las rutas."""
    target = Path(directory or os.getenv(SNAPSHOT_ENV) or DEFAULT_SNAPSHOT_DIR)
    target.mkdir(parents=True, exist_ok=True)
    paths = []
    for week in weeks:
        path = target / f"week_start={week.isoformat()}.json"
        payload = snapshot_payload(weekly, week, computed_at)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=int), encoding="utf-8")
        paths.append(str(path))
    return paths
