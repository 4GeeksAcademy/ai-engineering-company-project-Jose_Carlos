"""Telemetría: POST /telemetry/events — ingesta con persistencia (hito 16).

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
"""

import logging

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from services import telemetry
from services.telemetry import TelemetryEnvelope, TelemetryReceipt


logger = logging.getLogger("api.telemetry")

router = APIRouter(prefix="/telemetry", tags=["telemetry"])

# 100 eventos de ~1 KB caben de sobra; más que esto no es un lote del backoffice.
MAX_BODY_BYTES = 256 * 1024


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
