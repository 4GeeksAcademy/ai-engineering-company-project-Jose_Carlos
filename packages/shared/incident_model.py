"""Dominio del gestor de incidencias de TrackFlow (audit/CONTEXTS/CONTEXT-8-trackflow.es.md).

Lógica compartida: la usan la API (services/api/routes/incidents.py) y el seed
(scripts/seed_incidents.py). Valores permitidos, validación de campos, ciclo de vida
y transformación CSV → modelo viven solo aquí.
"""

from datetime import datetime, timezone


# =========================================================
# VALORES PERMITIDOS (exactos de CONTEXT-8)
# =========================================================

STATUSES = ("open", "in_progress", "resolved", "discarded")

ORIGINS = ("customer", "branch", "internal")

# Valor en base de datos → nombre para mostrar
BRANCHES = {
    "central": "Central",
    "la_warehouse": "Los Ángeles — Almacén",
    "la_office": "Los Ángeles — Oficina",
    "zaragoza_warehouse": "Zaragoza — Almacén",
    "zaragoza_office": "Zaragoza — Oficina",
}

CATEGORIES = (
    "lost_parcel",
    "delivery_failure",
    "inventory_discrepancy",
    "carrier_issue",
    "returns_issue",
    "warehouse_incident",
    "system_failure",
    "client_complaint",
    "other",
)

ALLOWED_VALUES = {
    "category": CATEGORIES,
    "status": STATUSES,
    "origin": ORIGINS,
    "branch": tuple(BRANCHES),
}

# Estado actual → estados a los que se puede avanzar. resolved y discarded son finales.
STATUS_TRANSITIONS = {
    "open": ("in_progress", "discarded"),
    "in_progress": ("resolved", "discarded"),
    "resolved": (),
    "discarded": (),
}

DEFAULT_STATUS = "open"
TITLE_MAX_LENGTH = 120
DESCRIPTION_MAX_LENGTH = 5000

REQUIRED_FIELDS = ("title", "description", "category", "origin", "branch")
FILTER_FIELDS = ("status", "origin", "branch", "category")


# =========================================================
# VALIDACIÓN DE CAMPOS
# =========================================================

def _error(field, code, message):
    return {"field": field, "code": code, "message": message}


def _invalid_value(field, value):
    allowed = ", ".join(ALLOWED_VALUES[field])
    return _error(
        field,
        "invalid_value",
        f"El valor '{value}' no está permitido en '{field}'. Valores permitidos: {allowed}.",
    )


def validate_incident_fields(data):
    """Valida los campos editables de una incidencia.

    Devuelve (incidencia_limpia, errores). Cada error identifica el campo:
    {"field", "code", "message"}. Si hay errores, la incidencia limpia es None.
    `status` es opcional y por defecto vale "open".
    """
    errors = []
    clean = {}

    for field in ("title", "description"):
        value = data.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            errors.append(_error(field, "required", f"El campo '{field}' es obligatorio."))
        elif not isinstance(value, str):
            errors.append(_error(field, "invalid_type", f"El campo '{field}' debe ser un texto."))
        else:
            clean[field] = value.strip()

    if len(clean.get("title", "")) > TITLE_MAX_LENGTH:
        errors.append(
            _error("title", "too_long", f"El título no puede superar los {TITLE_MAX_LENGTH} caracteres.")
        )
    if len(clean.get("description", "")) > DESCRIPTION_MAX_LENGTH:
        errors.append(
            _error(
                "description",
                "too_long",
                f"La descripción no puede superar los {DESCRIPTION_MAX_LENGTH} caracteres.",
            )
        )

    for field in ("category", "origin", "branch", "status"):
        value = data.get(field)
        if value is None or value == "":
            if field == "status":
                clean[field] = DEFAULT_STATUS
            else:
                errors.append(_error(field, "required", f"El campo '{field}' es obligatorio."))
        elif value not in ALLOWED_VALUES[field]:
            errors.append(_invalid_value(field, value))
        else:
            clean[field] = value

    return (None, errors) if errors else (clean, [])


def validate_filters(filters):
    """Valida los filtros opcionales del listado. Devuelve (filtros_activos, errores)."""
    errors = []
    active = {}
    for field in FILTER_FIELDS:
        value = filters.get(field)
        if value is None or value == "":
            continue
        if value not in ALLOWED_VALUES[field]:
            errors.append(_invalid_value(field, value))
        else:
            active[field] = value
    return active, errors


def validate_status_transition(current, new):
    """Devuelve None si el cambio de estado respeta el ciclo de vida, o el error si no."""
    if new is None or new == "":
        return _error("status", "required", "El campo 'status' es obligatorio.")
    if new not in STATUSES:
        return _invalid_value("status", new)
    allowed = STATUS_TRANSITIONS[current]
    if new not in allowed:
        if not allowed:
            detail = f"'{current}' es un estado final y no admite cambios."
        else:
            detail = f"Desde '{current}' solo se puede avanzar a: {', '.join(allowed)}."
        return _error(
            "status",
            "invalid_transition",
            f"No se puede cambiar el estado de '{current}' a '{new}'. {detail}",
        )
    return None


# =========================================================
# TRANSFORMACIÓN CSV (analizador) → MODELO
# =========================================================

SEED_ORIGIN = "customer"

CSV_STATUS_MAP = {
    "OPEN": "open",
    "CLOSED": "resolved",
    "DISCARDED": "discarded",
}

CSV_CATEGORY_MAP = {
    "LOST_PARCEL": "lost_parcel",
    "DELAYED_DELIVERY": "carrier_issue",
    "WRONG_ADDRESS": "delivery_failure",
    "RETURN_REQUEST": "returns_issue",
    "DAMAGE": "carrier_issue",
}

CSV_COUNTRY_BRANCH_MAP = {
    "US": "la_office",
    "ES": "zaragoza_office",
}


def csv_row_to_incident(row):
    """Transforma una fila ya validada del CSV del analizador en una incidencia del modelo.

    Devuelve (incidencia, errores). Si algún valor no se puede mapear, la incidencia es
    None y `errores` lista los motivos (textos para el informe de consola del seed).
    """
    errors = []

    description = row.get("description") or ""
    title = description.strip()[:TITLE_MAX_LENGTH].strip()
    if not title:
        errors.append("Empty title after trimming description")

    status = CSV_STATUS_MAP.get(row.get("status"))
    if status is None:
        errors.append(f"Unmappable status: {row.get('status')}")

    category = CSV_CATEGORY_MAP.get(row.get("category"))
    if category is None:
        errors.append(f"Unmappable category: {row.get('category')}")

    branch = CSV_COUNTRY_BRANCH_MAP.get(row.get("country"))
    if branch is None:
        errors.append(f"Unmappable country: {row.get('country')}")

    created_at = None
    try:
        # YYYY-MM-DD como medianoche UTC
        parsed = datetime.strptime((row.get("date") or "").strip(), "%Y-%m-%d")
        created_at = parsed.replace(tzinfo=timezone.utc).isoformat()
    except ValueError:
        errors.append(f"Invalid date (expected YYYY-MM-DD): {row.get('date')}")

    if errors:
        return None, errors

    return {
        "title": title,
        "description": description,
        "category": category,
        "status": status,
        "origin": SEED_ORIGIN,
        "branch": branch,
        "created_at": created_at,
        "updated_at": created_at,
    }, []
