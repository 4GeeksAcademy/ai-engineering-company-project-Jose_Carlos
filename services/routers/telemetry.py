"""Telemetría: POST /telemetry/events — ingesta (hito 16) y GET /telemetry/report — reporte (hito 17).

Recibe lotes `{"events": [...]}` del TelemetryService del backoffice, valida **cada evento por
separado** contra el contrato (`TelemetryEvent` + su allowlist de event-schemas.json), guarda
los válidos en `telemetry_events` con un único INSERT y responde
`{"received": N, "stored": M, "rejected": R}`. Misma URL y mismo envelope que el stub del
hito 15: el frontend no cambia.

- El cuerpo no se tipa como `list[TelemetryEvent]`: FastAPI validaría el lote entero antes
  del handler y un solo evento inválido devolvería 422 para todos. Se acepta el envelope de
  forma laxa (`TelemetryEnvelope`: una lista de valores crudos) y se valida evento a evento.
- 200 siempre que el envelope sea legible, aunque se rechacen eventos: el TelemetryService
  solo mira el código de estado, y un 4xx le haría descartar también los válidos.
- 422 si el envelope no lo es (no es JSON, no tiene `events`, más de 100 eventos); 413 si el
  cuerpo es enorme; 503 si Supabase falla, para que el backoffice reintente (sin duplicar
  filas: la clave primaria es el eventId).
- Sin JWT: `navigator.sendBeacon` (el envío al cerrar la pestaña) no puede añadir la cabecera
  Authorization. Por eso tampoco depende de la sesión: un lote nunca se pierde por haber
  caducado el token. El riesgo que eso abre (cualquiera puede enviar eventos) está en el plan.
- El cuerpo se lee a mano y no como parámetro de FastAPI: sendBeacon lo manda como
  `text/plain` (un `application/json` dispararía una petición previa CORS que sendBeacon no
  puede hacer), y FastAPI solo parsea como JSON los cuerpos `application/json`.

GET /telemetry/report (hito 17) sirve las métricas operacionales de
services/telemetry/analysis.py para un periodo `[start_date, end_date)`:

- El periodo se resuelve UNA vez aquí (`resolve_period`): sin parámetros, los últimos 7 días
  hasta ahora, en UTC. Cada métrica lo recibe ya resuelto y no aplica su propia ventana.
- El endpoint no calcula nada: llama a `analysis.build_report` a través de la caché en
  memoria de la API (`response_cache`, TTL de 60 s). La clave son los parámetros tal como se
  pidieron (normalizados a UTC); sin parámetros la clave es fija, así que el "últimos 7 días"
  también se sirve de caché durante 60 s (su `period.to` es el instante en que se calculó).
  No se invalida al ingerir eventos: el TTL es el retraso máximo aceptado.
- Requiere sesión (JWT): son datos internos de operación, para el equipo técnico.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.exc import SQLAlchemyError

from services import telemetry
from services.api.cache import make_key, response_cache
from services.api.security import get_current_user
from services.telemetry import TelemetryEnvelope, TelemetryReceipt, analysis


logger = logging.getLogger("api.telemetry")

router = APIRouter(prefix="/telemetry", tags=["telemetry"])

# 100 eventos de ~1 KB caben de sobra; más que esto no es un lote del backoffice.
MAX_BODY_BYTES = 256 * 1024

REPORT_PATH = "/telemetry/report"
REPORT_TTL_SECONDS = 60
DEFAULT_REPORT_WINDOW = timedelta(days=7)


@router.post("/events", response_model=TelemetryReceipt)
async def receive_events(request: Request) -> TelemetryReceipt:
    raw = await request.body()
    if len(raw) > MAX_BODY_BYTES:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="Telemetry batch too large")
    try:
        envelope = TelemetryEnvelope.model_validate_json(raw)
    except ValidationError as error:
        # Mismo 422 que el resto de la API, sin devolver lo que se envió.
        raise RequestValidationError(error.errors(include_url=False, include_context=False, include_input=False))
    try:
        # La escritura en Supabase es síncrona: fuera del bucle de eventos.
        return await run_in_threadpool(telemetry.ingest_batch, envelope.events)
    except SQLAlchemyError as error:
        logger.error("telemetry_storage_failed error=%s events=%d", type(error).__name__, len(envelope.events))
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Telemetry storage unavailable")


# =========================================================
# GET /telemetry/report (hito 17)
# =========================================================


class ReportPeriod(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_: str = Field(alias="from", description="Inicio del periodo (incluido), ISO 8601 UTC.")
    to: str = Field(description="Fin del periodo (excluido), ISO 8601 UTC.")


class TelemetryReport(BaseModel):
    period: ReportPeriod
    metrics: dict[str, list[dict[str, Any]]] = Field(
        description="Una lista de filas por métrica (services/telemetry/analysis.py → METRICS), cada una con su `date`."
    )


def _utc(moment: datetime | None) -> datetime | None:
    """Sin zona horaria se interpreta como UTC; con ella, se pasa a UTC."""
    if moment is None:
        return None
    return moment.replace(tzinfo=timezone.utc) if moment.tzinfo is None else moment.astimezone(timezone.utc)


def resolve_period(start_date: datetime | None, end_date: datetime | None, now: datetime) -> tuple[datetime, datetime]:
    """El periodo del reporte: `end` por defecto ahora y `start` por defecto `end - 7 días`."""
    end = _utc(end_date) or now
    start = _utc(start_date) or end - DEFAULT_REPORT_WINDOW
    try:
        analysis.check_window(start, end)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error))
    return start, end


def _compute_report(start_date: datetime | None, end_date: datetime | None) -> dict[str, Any]:
    start, end = resolve_period(start_date, end_date, datetime.now(timezone.utc))
    logger.info("telemetry_report computed from=%s to=%s", start.isoformat(), end.isoformat())
    return analysis.build_report(start, end)


@router.get("/report", response_model=TelemetryReport, response_model_by_alias=True)
def telemetry_report(
    start_date: datetime | None = Query(None, description="Inicio ISO 8601 (incluido). Por defecto, end_date − 7 días."),
    end_date: datetime | None = Query(None, description="Fin ISO 8601 (excluido). Por defecto, ahora (UTC)."),
    _user: dict = Depends(get_current_user),
):
    # Ruta síncrona: FastAPI la ejecuta en el threadpool, fuera del bucle de eventos.
    start_date, end_date = _utc(start_date), _utc(end_date)
    key = make_key(REPORT_PATH, {
        "start_date": start_date.isoformat() if start_date else None,
        "end_date": end_date.isoformat() if end_date else None,
    })
    try:
        return response_cache.get_or_set(key, REPORT_TTL_SECONDS, lambda: _compute_report(start_date, end_date))
    except SQLAlchemyError as error:
        logger.error("telemetry_report_failed error=%s", type(error).__name__)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Telemetry storage unavailable")
