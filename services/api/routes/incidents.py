import logging
from collections import Counter
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from packages.shared.incident_model import (
    BRANCHES,
    CATEGORIES,
    ORIGINS,
    STATUSES,
    validate_filters,
    validate_incident_fields,
    validate_status_transition,
)
from services.api import incident_service, store
from services.api.security import get_current_user


logger = logging.getLogger(__name__)

GENERIC_ERROR = "Se ha producido un error interno. Inténtalo de nuevo más tarde."
SEMANTIC_UNAVAILABLE = "La búsqueda por similitud no está disponible en este momento."


class IncidentValidationError(Exception):
    """Errores de validación: lista de {"field", "code", "message"} → respuesta 400."""

    def __init__(self, errors: list[dict]):
        super().__init__("Incident validation error")
        self.errors = errors


def _validation_response(errors: list[dict]) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"detail": "La petición contiene campos no válidos.", "errors": errors},
    )


class IncidentRoute(APIRoute):
    """Manejo de errores de las rutas de incidencias.

    - Validación (la nuestra o la de FastAPI) → 400 con el campo problemático.
    - Cualquier excepción no controlada → 500 con un mensaje genérico; el detalle
      solo va al log del servidor, nunca al cliente.
    """

    def get_route_handler(self):
        original_handler = super().get_route_handler()

        async def handler(request: Request):
            try:
                return await original_handler(request)
            except IncidentValidationError as error:
                return _validation_response(error.errors)
            except RequestValidationError as error:
                return _validation_response(
                    [
                        {
                            "field": str(item["loc"][-1]) if item.get("loc") else "body",
                            "code": "invalid_value",
                            "message": "El valor enviado no tiene el formato esperado.",
                        }
                        for item in error.errors()
                    ]
                )
            except HTTPException:
                raise
            except Exception:
                logger.exception("Error no controlado en %s %s", request.method, request.url.path)
                return JSONResponse(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    content={"detail": GENERIC_ERROR},
                )

        return handler


# El prefijo /api/incidents se añade en main.py con app.include_router(...)
# Todas las rutas de incidencias requieren un JWT válido, como el resto del backoffice.
router = APIRouter(
    tags=["incidents"],
    dependencies=[Depends(get_current_user)],
    route_class=IncidentRoute,
)


def _now_utc() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _not_found(incident_id: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Incident {incident_id} not found",
    )


def _get_or_404(incident_id: int) -> dict:
    incident = store.get_incident_by_id(incident_id)
    if incident is None:
        raise _not_found(incident_id)
    return incident


def _checked_filters(**filters) -> dict:
    active, errors = validate_filters(filters)
    if errors:
        raise IncidentValidationError(errors)
    return active


def _semantic(operation):
    """Ejecuta una operación de embeddings; si falla, 503 con un mensaje claro."""
    try:
        return operation()
    except Exception:
        logger.exception("Fallo en la capa de embeddings")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=SEMANTIC_UNAVAILABLE,
        )


# =========================================================
# GESTIÓN
# =========================================================


@router.post("", status_code=status.HTTP_201_CREATED)
def create_incident(payload: dict = Body(...)):
    incident, errors = validate_incident_fields(payload)
    if errors:
        raise IncidentValidationError(errors)

    # id, created_at y updated_at los pone siempre el servidor.
    now = _now_utc()
    created = store.create_incident({**incident, "created_at": now, "updated_at": now})
    incident_service.index_incident_safely()
    return created


@router.get("")
def list_incidents(
    status: str | None = None,
    origin: str | None = None,
    branch: str | None = None,
    category: str | None = None,
):
    # Los filtros se combinan con AND. Las más recientes primero.
    filters = _checked_filters(status=status, origin=origin, branch=branch, category=category)
    incidents = [
        incident
        for incident in store.get_all_incidents()
        if all(incident[field] == value for field, value in filters.items())
    ]
    incidents.sort(key=lambda incident: (incident["created_at"], incident["id"]), reverse=True)
    return incidents


# Las rutas fijas van antes de /{incident_id} para que no se interpreten como un id.
@router.get("/summary")
def incidents_summary():
    incidents = store.get_all_incidents()

    def totals(field: str, values) -> dict:
        # Todos los valores posibles aparecen siempre, con 0 si no hay incidencias.
        counts = Counter(incident[field] for incident in incidents)
        return {value: counts.get(value, 0) for value in values}

    return {
        "total": len(incidents),
        "by_status": totals("status", STATUSES),
        "by_category": totals("category", CATEGORIES),
        "by_origin": totals("origin", ORIGINS),
        "by_branch": totals("branch", BRANCHES),
    }


# =========================================================
# CAPA SEMÁNTICA (embeddings)
# =========================================================


@router.get("/search")
def search_incidents(
    q: str = "",
    limit: int = Query(20, ge=1, le=100),
    status: str | None = None,
    origin: str | None = None,
    branch: str | None = None,
    category: str | None = None,
):
    """Búsqueda por significado, combinable con los mismos filtros que el listado."""
    filters = _checked_filters(status=status, origin=origin, branch=branch, category=category)
    query = q.strip()
    if not query:
        raise IncidentValidationError(
            [{"field": "q", "code": "required", "message": "Escribe un texto para buscar."}]
        )
    return _semantic(lambda: incident_service.search(query, limit, filters))


@router.get("/duplicates")
def duplicate_groups():
    """Grupos de incidencias activas que parecen describir el mismo problema."""
    return _semantic(incident_service.duplicate_groups)


@router.post("/suggest")
def suggest_for_draft(payload: dict = Body(...)):
    """Para un borrador (título y/o descripción): incidencias similares y categoría sugerida."""
    title = payload.get("title") if isinstance(payload.get("title"), str) else ""
    description = payload.get("description") if isinstance(payload.get("description"), str) else ""
    if not (title.strip() or description.strip()):
        raise IncidentValidationError(
            [
                {
                    "field": "description",
                    "code": "required",
                    "message": "Escribe un título o una descripción para buscar incidencias similares.",
                }
            ]
        )

    similar = _semantic(lambda: incident_service.similar_to_text(title, description))
    return {
        "similar": similar,
        "suggested_category": incident_service.suggest_category(similar),
    }


# =========================================================
# DETALLE Y ESTADO
# =========================================================


@router.get("/{incident_id}")
def get_incident(incident_id: int):
    return _get_or_404(incident_id)


@router.get("/{incident_id}/similar")
def similar_incidents(incident_id: int, limit: int = Query(5, ge=1, le=20)):
    """Casos pasados parecidos, para reutilizar resoluciones o detectar problemas recurrentes."""
    incident = _get_or_404(incident_id)
    return _semantic(lambda: incident_service.similar_to_incident(incident, limit))


@router.patch("/{incident_id}/status")
def update_incident_status(incident_id: int, payload: dict = Body(...)):
    incident = _get_or_404(incident_id)

    error = validate_status_transition(incident["status"], payload.get("status"))
    if error:
        raise IncidentValidationError([error])

    return store.update_incident(incident_id, {"status": payload["status"], "updated_at": _now_utc()})
