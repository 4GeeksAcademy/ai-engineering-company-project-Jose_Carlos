"""Telemetría (TELEMETRY_PLAN.md): envelope, recepción de lotes y eventos que emite la API.

- `TelemetryEvent` es el Event Envelope de la Fase 1 (sección 4 del plan). Lo usa el stub
  POST /telemetry/events (services/routers/telemetry.py) y lo reutilizará sin cambios la
  implementación con persistencia.
- `record_events()` es el único sitio por el que pasa todo evento, venga del backoffice o de
  la propia API: hoy solo valida y escribe en el log; la persistencia llegará aquí.
- `emit()` construye y registra los eventos que solo puede ver el servidor (cruce de umbral,
  discrepancia de inventario, intento de fijar stock). Nunca lanza: la telemetría no puede
  romper un registro de stock.
- La correlación (`requestId`, `sessionId`) de la petición en curso vive en ContextVar; la
  rellena el middleware de services/api/main.py a partir de X-Request-Id y X-Session-Id.
"""

import json
import logging
import re
import unicodedata
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from jsonschema import Draft7Validator
from pydantic import BaseModel, ConfigDict, Field

from services.api import config


logger = logging.getLogger("api.telemetry")

# El contrato: el mismo archivo que valida el test del plan (tests/telemetry).
SCHEMAS_PATH = Path(__file__).resolve().parents[1] / "event-schemas.json"

UUID_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
UUID_V4_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
TIMESTAMP_PATTERN = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"
EVENT_TYPE_PATTERN = r"^[a-z]+(_[a-z]+)+$"
SEMVER_PATTERN = r"^\d+\.\d+\.\d+$"

# Un lote del backoffice lleva como mucho 20 eventos; el margen cubre el flush de sendBeacon
# al cerrar la pestaña, que manda lo que quede en la cola.
MAX_BATCH_EVENTS = 100


# =========================================================
# ENVELOPE
# =========================================================


class TelemetryEvent(BaseModel):
    """Event Envelope estándar (TELEMETRY_PLAN.md §4.1). Las claves de primer nivel son cerradas."""

    model_config = ConfigDict(extra="forbid")

    eventId: str = Field(pattern=UUID_V4_PATTERN, description="UUID v4 generado al capturar. Clave de idempotencia.")
    timestamp: str = Field(pattern=TIMESTAMP_PATTERN, description="Momento de la captura, ISO 8601 UTC con milisegundos.")
    sessionId: str | None = Field(pattern=UUID_PATTERN, description="Sesión del backoffice; null sin backoffice.")
    userId: str | None = Field(pattern=UUID_PATTERN, description="Id del usuario en TinyDB; null antes de autenticarse.")
    event_type: str = Field(pattern=EVENT_TYPE_PATTERN, max_length=64, description="Taxonomía entidad_acción.")
    schemaVersion: str = Field(pattern=SEMVER_PATTERN, description="Versión del esquema de ese evento.")
    requestId: str = Field(pattern=UUID_PATTERN, description="Correlación con la petición HTTP.")
    source: Literal["api", "backoffice_web"]
    environment: Literal["development", "test", "production"]
    properties: dict[str, Any] = Field(description="Payload del evento; su allowlist está en event-schemas.json.")


class TelemetryBatch(BaseModel):
    """Cuerpo de POST /telemetry/events: `{"events": [...]}`."""

    model_config = ConfigDict(extra="forbid")

    events: list[TelemetryEvent] = Field(min_length=1, max_length=MAX_BATCH_EVENTS)


class TelemetryReceipt(BaseModel):
    received: int = Field(description="Número de eventos del lote.")


# =========================================================
# VALIDACIÓN CONTRA event-schemas.json
# =========================================================


@lru_cache(maxsize=1)
def _schemas() -> dict | None:
    try:
        return json.loads(SCHEMAS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("event-schemas.json no disponible en %s: solo se valida el envelope", SCHEMAS_PATH)
        return None


@lru_cache(maxsize=1)
def _validator() -> Draft7Validator | None:
    schemas = _schemas()
    return Draft7Validator(schemas) if schemas else None


def schema_version(event_type: str) -> str:
    """Versión vigente del esquema de un evento (el `const` de su schemaVersion)."""
    schemas = _schemas() or {}
    definition = schemas.get("definitions", {}).get(event_type, {})
    return definition.get("properties", {}).get("schemaVersion", {}).get("const", "1.0.0")


def schema_violations(event: dict) -> list[str]:
    """Rutas de las claves que no cumplen el esquema del evento (nunca sus valores)."""
    validator = _validator()
    if validator is None:
        return []
    schemas = _schemas()
    definition = schemas["definitions"].get(event.get("event_type", ""))
    if definition is None:
        return ["event_type: no está en el catálogo"]
    # Contra el esquema concreto del evento (y no contra el oneOf de la raíz), para que el
    # error diga qué clave falla y no "no cumple ninguno de los 26 esquemas".
    errors = Draft7Validator({**definition, "definitions": schemas["definitions"]}).iter_errors(event)
    return sorted("/".join(str(part) for part in error.absolute_path) or "(evento)" for error in errors)


# =========================================================
# RECEPCIÓN: el único punto por el que pasa todo evento
# =========================================================


def record_events(events: list[TelemetryEvent]) -> list[TelemetryEvent]:
    """Registra un lote y devuelve los eventos válidos según su allowlist.

    Stub de la Fase 2: no persiste nada. Escribe en el log cuántos eventos llegan y de qué
    tipo, y avisa de los que se salen de su esquema (sin escribir sus valores, que podrían ser
    justo el dato que no debía salir). En la Fase 3, aquí se guardarán los válidos.
    """
    valid = []
    for event in events:
        violations = schema_violations(event.model_dump())
        if violations:
            logger.warning("telemetry_schema_violation event_type=%s fields=%s", event.event_type, ",".join(violations))
        else:
            valid.append(event)
    sources = sorted({event.source for event in events})
    logger.info(
        "telemetry batch received=%d valid=%d source=%s event_types=%s",
        len(events), len(valid), ",".join(sources), ",".join(event.event_type for event in events),
    )
    return valid


# =========================================================
# CORRELACIÓN DE LA PETICIÓN EN CURSO
# =========================================================

_request_id: ContextVar[str | None] = ContextVar("telemetry_request_id", default=None)
_session_id: ContextVar[str | None] = ContextVar("telemetry_session_id", default=None)


def _uuid_or_none(value: str | None) -> str | None:
    value = (value or "").strip().lower()
    return value if re.fullmatch(UUID_PATTERN, value) else None


def bind_request(request_id: str | None, session_id: str | None) -> str:
    """Fija la correlación de la petición actual y devuelve su requestId (el recibido o uno nuevo)."""
    request_id = _uuid_or_none(request_id) or str(uuid.uuid4())
    _request_id.set(request_id)
    _session_id.set(_uuid_or_none(session_id))
    return request_id


def current_session_id() -> str | None:
    return _session_id.get()


# =========================================================
# EVENTOS DE SERVIDOR
# =========================================================


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def emit(event_type: str, properties: dict[str, Any], *, user_id: str | None) -> None:
    """Emite un evento con `source = "api"`. Si no cumple su esquema, se descarta (plan §4.6)."""
    try:
        event = TelemetryEvent(
            eventId=str(uuid.uuid4()),
            timestamp=_now_iso(),
            sessionId=_session_id.get(),
            userId=user_id,
            event_type=event_type,
            schemaVersion=schema_version(event_type),
            # Fuera de una petición (seed, scripts) no hay requestId: cada evento lleva uno nuevo.
            requestId=_request_id.get() or str(uuid.uuid4()),
            source="api",
            environment=config.TELEMETRY_ENVIRONMENT,
            properties=properties,
        )
        violations = schema_violations(event.model_dump())
        if violations:
            logger.error("telemetry_schema_violation event_type=%s fields=%s (no se emite)", event_type, ",".join(violations))
            return
        record_events([event])
    except Exception:
        # La telemetría nunca rompe la operación de negocio que la dispara.
        logger.exception("No se pudo emitir el evento de telemetría %s", event_type)


# =========================================================
# VOCABULARIO DEL BRIEFING (TELEMETRY_PLAN.md §4.3)
# =========================================================

WAREHOUSES = {"LA": "los_angeles", "ZGZ": "zaragoza"}
COUNTRIES = {"los_angeles": "US", "zaragoza": "ES"}


def client_id(client_name: str) -> str:
    """Slug determinista de la marca cliente: `GlowLab Cosmetics` → `glowlab_cosmetics`."""
    ascii_name = unicodedata.normalize("NFKD", client_name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", ascii_name.lower()).strip("_")


def inventory_properties(sku, warehouse_code: str, quantity: int | None) -> dict[str, Any]:
    """Los campos mínimos del BRIEFING para un SKU (objeto con sku, client_name y category)."""
    warehouse = WAREHOUSES[warehouse_code]
    return {
        "warehouse": warehouse,
        "country": COUNTRIES[warehouse],
        "client_id": client_id(sku.client_name),
        "product_id": sku.sku,
        "product_category": sku.category,
        "quantity": quantity,
    }
