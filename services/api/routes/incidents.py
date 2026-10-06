import logging
from collections import Counter
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Query, status

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
from services.api.embeddings import EmbeddingsUnavailable
from services.api.errors import IncidentValidationError
from services.api.security import get_current_user


logger = logging.getLogger(__name__)

SEMANTIC_UNAVAILABLE = "La búsqueda por similitud no está disponible en este momento."


# El prefijo /api/incidents se añade en main.py con app.include_router(...)
# Todas las rutas de incidencias requieren un JWT válido, como el resto del backoffice.
# Los errores (400 de validación, 500 genérico) se responden en services/api/errors.py.
router = APIRouter(tags=["incidents"], dependencies=[Depends(get_current_user)])


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
    """Ejecuta una operación de embeddings; si el proveedor falla, 503 con un mensaje claro.

    Cualquier otro error (un fallo de programación, por ejemplo) sigue su curso hasta el 500.
    """
    try:
        return operation()
    except EmbeddingsUnavailable:
        logger.exception("El proveedor de embeddings no está disponible")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=SEMANTIC_UNAVAILABLE,
        )


# =========================================================
# GESTIÓN
# =========================================================


@router.post("", status_code=status.HTTP_201_CREATED)
def create_incident(background_tasks: BackgroundTasks, payload: dict = Body(...)):
    incident, errors = validate_incident_fields(payload)
    if errors:
        raise IncidentValidationError(errors)

    # id, created_at y updated_at los pone siempre el servidor.
    now = _now_utc()
    created = store.create_incident({**incident, "created_at": now, "updated_at": now})
    # El embedding se calcula después de responder: cargar el modelo puede tardar.
    background_tasks.add_task(incident_service.index_pending)
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


@router.get("/semantic-status")
def semantic_status():
    """Proveedor de embeddings activo, si está en modo degradado e incidencias sin indexar."""
    return incident_service.semantic_status()


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
