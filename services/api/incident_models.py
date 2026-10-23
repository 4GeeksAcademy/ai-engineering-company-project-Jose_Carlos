"""Schemas Pydantic del gestor de incidencias (/api/incidents).

Salida: cada ruta declara uno de estos schemas como `response_model`, así FastAPI solo deja
salir los campos listados aquí aunque el handler devuelva el documento completo de TinyDB.

Entrada: la validación la sigue haciendo packages/shared/incident_model.py (compartida con
el seed), que ya descarta `id`, `created_at` y `updated_at` y responde 400 con
{field, code} — el contrato que traduce el backoffice. Los schemas de entrada de este
módulo solo DOCUMENTAN ese cuerpo en OpenAPI (ver `json_body`); no validan.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from packages.shared.incident_model import (
    BRANCHES,
    CATEGORIES,
    DESCRIPTION_MAX_LENGTH,
    ORIGINS,
    STATUSES,
    TITLE_MAX_LENGTH,
)


Category = Literal[CATEGORIES]
Status = Literal[STATUSES]
Origin = Literal[ORIGINS]
Branch = Literal[tuple(BRANCHES)]

# Se guarda y se devuelve como texto ISO 8601 tal cual (p. ej. 2026-10-01T08:00:00+00:00):
# con `datetime` Pydantic lo reescribiría en otro formato y cambiaría el contrato.
Timestamp = Annotated[str, Field(json_schema_extra={"format": "date-time"})]


def json_body(model: type[BaseModel]) -> dict:
    """`openapi_extra` que documenta el cuerpo JSON de una ruta con el schema de `model`."""
    return {
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": model.model_json_schema()}},
        }
    }


# =========================================================
# ENTRADA (solo documentación)
# =========================================================


class IncidentCreate(BaseModel):
    title: str = Field(max_length=TITLE_MAX_LENGTH)
    description: str = Field(max_length=DESCRIPTION_MAX_LENGTH)
    category: Category
    origin: Origin
    branch: Branch
    status: Status = "open"


class IncidentStatusUpdate(BaseModel):
    status: Status


class IncidentSuggestRequest(BaseModel):
    """Borrador de incidencia: al menos uno de los dos textos no vacío."""

    title: str = ""
    description: str = ""


# =========================================================
# SALIDA
# =========================================================


class IncidentListItem(BaseModel):
    """Fila del listado: todo lo que pinta la tabla (sin `updated_at`, que no se muestra)."""

    id: int
    title: str
    description: str
    category: Category
    status: Status
    origin: Origin
    branch: Branch
    created_at: Timestamp


class IncidentRead(IncidentListItem):
    """Detalle completo: alta, detalle y cambio de estado."""

    updated_at: Timestamp


class IncidentSearchResult(IncidentListItem):
    score: float = Field(description="Similitud con la consulta (0-1).")


class SimilarIncident(BaseModel):
    """Incidencia parecida (a otra ya registrada o a un borrador): proyección sin textos largos."""

    id: int
    title: str
    category: Category
    status: Status
    branch: Branch
    created_at: Timestamp
    score: float
    possible_duplicate: bool


class IncidentSummary(BaseModel):
    total: int
    by_status: dict[str, int]
    by_category: dict[str, int]
    by_origin: dict[str, int]
    by_branch: dict[str, int]


class SemanticStatus(BaseModel):
    provider: str
    degraded: bool = Field(description="True: el modelo configurado no ha cargado y se busca solo por palabras.")
    indexed: int
    pending: int


class DuplicateGroup(BaseModel):
    size: int
    title: str
    category: Category
    branches: list[Branch]
    incident_ids: list[int]


class CategorySuggestion(BaseModel):
    value: Category
    confidence: float


class IncidentSuggestion(BaseModel):
    similar: list[SimilarIncident]
    suggested_category: CategorySuggestion | None
