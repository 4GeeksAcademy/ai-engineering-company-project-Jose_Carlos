"""Telemetría: POST /telemetry/events — STUB de verificación (hito 15).

Recibe lotes `{"events": [...]}` del TelemetryService del backoffice, valida el envelope
(`TelemetryEvent`), escribe en el log cuántos eventos llegan y de qué tipo, y responde
`{"received": N}`. Todavía no guarda nada: la persistencia es la Fase 3 y llegará en
`services.telemetry.record_events`, sin cambiar ni este contrato ni el frontend.

- Sin JWT: `navigator.sendBeacon` (el envío al cerrar la pestaña) no puede añadir la cabecera
  Authorization. Por eso tampoco depende de la sesión: un lote nunca se pierde por haber
  caducado el token. El riesgo que eso abre (cualquiera puede enviar eventos) está en el plan.
- El cuerpo se lee a mano y no como parámetro de FastAPI: sendBeacon lo manda como
  `text/plain` (un `application/json` dispararía una petición previa CORS que sendBeacon no
  puede hacer), y FastAPI solo parsea como JSON los cuerpos `application/json`.
"""

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from services.telemetry import TelemetryBatch, TelemetryReceipt, record_events


router = APIRouter(prefix="/telemetry", tags=["telemetry"])

# 100 eventos de ~1 KB caben de sobra; más que esto no es un lote del backoffice.
MAX_BODY_BYTES = 256 * 1024


@router.post("/events", response_model=TelemetryReceipt)
async def receive_events(request: Request) -> TelemetryReceipt:
    raw = await request.body()
    if len(raw) > MAX_BODY_BYTES:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="Telemetry batch too large")
    try:
        batch = TelemetryBatch.model_validate_json(raw)
    except ValidationError as error:
        # Mismo 422 que el resto de la API, sin devolver lo que se envió.
        raise RequestValidationError(error.errors(include_url=False, include_context=False, include_input=False))
    record_events(batch.events)
    return TelemetryReceipt(received=len(batch.events))
