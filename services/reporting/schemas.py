"""Modelos de respuesta de /reporting (contrato del BRIEFING §6 y PIPELINE_DESIGN.md §11.2)."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class WeeklyPerformanceEntry(BaseModel):
    """Una combinación almacén × cliente de la semana, con los cuatro KPIs del BRIEFING §2."""

    warehouse: Literal["los_angeles", "zaragoza"]
    client_id: str
    inbound_units_count: int = Field(description="Volumen de entrada: unidades recibidas (suma de quantity).")
    outbound_orders_count: int = Field(description="Throughput de salida: pedidos despachados.")
    stockout_events_count: int = Field(description="Frecuencia de quiebre de stock: cruces del mínimo.")
    discrepancy_events_count: int = Field(description="Discrepancias de inventario detectadas (numerador).")
    discrepancy_rate: float = Field(description="Tasa de discrepancia: discrepancias / pedidos de salida (0 sin salidas).")


class WeeklyPerformanceReport(BaseModel):
    week_start: str = Field(description="Lunes (UTC) de la semana ISO, YYYY-MM-DD.")
    computed_at: str | None = Field(None, description="Cuándo se calcularon las filas por última vez (ISO 8601 UTC).")
    entries: list[WeeklyPerformanceEntry]


class PipelineRun(BaseModel):
    run_id: str
    pipeline_name: str
    trigger: Literal["scheduled", "manual", "backfill"]
    triggered_by: str | None
    status: Literal["running", "completed", "failed"]
    started_at: str
    finished_at: str | None
    weeks_processed: list[str]
    source_watermark: str
    events_extracted: int
    events_discarded: int
    events_deduplicated: int
    rows_upserted: int
    rows_deleted: int
    error_stage: str | None
    error_message: str | None
    warnings: list[dict[str, Any]]
    parameters: dict[str, Any]
    code_version: str | None


class LatestPipelineRun(BaseModel):
    pipeline_name: str
    latest_run: PipelineRun
    latest_successful_run_id: str | None


class PipelineRunRequest(BaseModel):
    week_start: str | None = Field(None, description="Lunes de la semana (YYYY-MM-DD). Por defecto, la última cerrada.")
    lookback_weeks: int = Field(1, description="Semanas anteriores a recalcular también (0-12).")


class PipelineRunScheduled(BaseModel):
    pipeline_name: str
    status: Literal["scheduled"]
    mode: Literal["local", "deployment"]
    flow_run_id: str | None = Field(description="Id del flow run en Prefect (modo deployment); en modo local se ve en /latest.")
