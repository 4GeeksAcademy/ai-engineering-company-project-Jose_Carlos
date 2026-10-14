"""Manejo de errores común a toda la API.

- Excepción no controlada → 500 con un mensaje genérico en JSON; el detalle solo va al log.
- Validación del gestor de incidencias → 400 con el campo problemático.
- Base de datos de inventario (Supabase) inalcanzable → 503 con un mensaje claro.
- Validación de FastAPI en el resto de rutas → 422 como siempre, pero sin el campo `input`
  (devolvería al cliente lo que envió, que puede ser una contraseña).
"""

import logging

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError


logger = logging.getLogger(__name__)

GENERIC_ERROR = "Se ha producido un error interno. Inténtalo de nuevo más tarde."
INVENTORY_UNAVAILABLE = "El inventario no está disponible en este momento. Inténtalo de nuevo en unos minutos."

INCIDENTS_PREFIX = "/api/incidents"


class IncidentValidationError(Exception):
    """Errores de validación: lista de {"field", "code", "message"} → respuesta 400."""

    def __init__(self, errors: list[dict]):
        super().__init__("Incident validation error")
        self.errors = errors


def _incident_validation_response(errors: list[dict]) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"detail": "La petición contiene campos no válidos.", "errors": errors},
    )


async def _handle_incident_validation(request: Request, error: IncidentValidationError) -> JSONResponse:
    return _incident_validation_response(error.errors)


async def _handle_request_validation(request: Request, error: RequestValidationError) -> JSONResponse:
    if request.url.path.startswith(INCIDENTS_PREFIX):
        return _incident_validation_response(
            [
                {
                    "field": str(item["loc"][-1]) if item.get("loc") else "body",
                    "code": "invalid_value",
                    "message": "El valor enviado no tiene el formato esperado.",
                }
                for item in error.errors()
            ]
        )

    details = [{key: value for key, value in item.items() if key != "input"} for item in error.errors()]
    return JSONResponse(
        status_code=422,
        content={"detail": jsonable_encoder(details)},
    )


async def _handle_database_unavailable(request: Request, error: OperationalError) -> JSONResponse:
    # Sin red, Supabase en pausa o credenciales caducadas. El detalle (host, usuario) solo va al log.
    logger.error("Base de datos de inventario no disponible en %s %s", request.method, request.url.path, exc_info=error)
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": INVENTORY_UNAVAILABLE},
    )


async def _handle_unexpected(request: Request, error: Exception) -> JSONResponse:
    logger.error("Error no controlado en %s %s", request.method, request.url.path, exc_info=error)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": GENERIC_ERROR},
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(IncidentValidationError, _handle_incident_validation)
    app.add_exception_handler(RequestValidationError, _handle_request_validation)
    app.add_exception_handler(OperationalError, _handle_database_unavailable)
    app.add_exception_handler(Exception, _handle_unexpected)
