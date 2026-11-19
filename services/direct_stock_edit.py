"""Captura de `direct_stock_edit_rejected` (métrica obligatoria del BRIEFING).

El stock nunca se fija: no hay ninguna pantalla que permita intentarlo, así que el único
camino es la API. El servidor rechaza los dos casos sin ayuda de este módulo; aquí solo se
reconocen y se emite el evento:

(a) `method_not_allowed`: PUT, PATCH o DELETE sobre /inventory/products… o /inventory/orders…
    (rutas que no existen a propósito: la API responde 404 o 405). Lo llama el middleware de
    services/api/main.py con la respuesta ya calculada.
(b) `forbidden_stock_field`: un POST a /inventory/… con un campo de stock en el cuerpo
    (`current_stock`, `stock`…), que Pydantic rechaza con 422 `extra_forbidden`. Lo llama el
    manejador de validación de services/api/errors.py.

Solo se emite para usuarios autenticados: la hipótesis es "el personal de almacén intenta
saltarse la trazabilidad", y una petición sin sesión no es de nadie del personal.
Nunca lanza: si algo falla, la respuesta al cliente es la misma.
"""

import logging
import re
from types import SimpleNamespace

from fastapi import Request
from starlette.concurrency import run_in_threadpool

from services import telemetry
from services.api import user_service
from services.api.security import decode_access_token
from services.database import get_db
from services.models import CATEGORIES, SKU, WAREHOUSES


logger = logging.getLogger("api.telemetry")

STOCK_FIELDS = ("current_stock", "stock", "stock_by_warehouse", "initial_stock")
# En el alta de un SKU, `quantity` también es fijar stock (un SKU nace siempre con 0).
PRODUCT_STOCK_FIELDS = (*STOCK_FIELDS, "quantity")

EDIT_METHODS = {"PUT", "PATCH", "DELETE"}
INVENTORY_RESOURCE = re.compile(r"^/inventory/(products|orders)(/|$)")
PRODUCT_PATH = re.compile(r"^/inventory/products/(\d+)$")


def is_method_attempt(method: str, path: str, status_code: int) -> bool:
    """Caso (a): la API ha rechazado un PUT/PATCH/DELETE sobre SKUs o movimientos."""
    return method in EDIT_METHODS and status_code in (404, 405) and bool(INVENTORY_RESOURCE.match(path))


def stock_fields_in_validation_errors(path: str, errors: list[dict]) -> list[str]:
    """Caso (b): campos de stock rechazados por `extra_forbidden` en un POST a /inventory."""
    allowed = PRODUCT_STOCK_FIELDS if path == "/inventory/products" else STOCK_FIELDS
    fields = {str(error["loc"][-1]) for error in errors if error.get("type") == "extra_forbidden" and error.get("loc")}
    return [field for field in allowed if field in fields]


def _route_template(request: Request) -> str:
    route = request.scope.get("route")
    if route is not None and getattr(route, "path", None):
        return route.path
    # Sin ruta (404/405): se sustituyen los ids por un marcador, nunca se envían.
    path = PRODUCT_PATH.sub("/inventory/products/{sku_id}", request.url.path)
    return re.sub(r"/\d+(?=/|$)", "/{id}", path)


def _user(request: Request) -> dict | None:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    user_id = decode_access_token(token)
    return user_service.get_user_by_id(user_id) if user_id else None


def _attempted_quantity(body: dict, fields: list[str]) -> int | None:
    for field in fields:
        value = body.get(field)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
    return None


def _sku_from_body(body: dict):
    """En el alta de un SKU, el producto aún no existe: sus datos vienen en el cuerpo."""
    if body.get("warehouse") not in WAREHOUSES or body.get("category") not in CATEGORIES:
        return None
    if not isinstance(body.get("client_name"), str) or not isinstance(body.get("sku"), str):
        return None
    if not body["client_name"].strip() or not 0 < len(body["sku"].strip()) <= 64:
        return None
    return SimpleNamespace(sku=body["sku"].strip(), client_name=body["client_name"], category=body["category"]), body["warehouse"]


def _resolve_sku(request: Request, body: dict):
    """(SKU, almacén) del intento, o None si no se puede saber de qué SKU se trata."""
    match = PRODUCT_PATH.match(request.url.path)
    sku_id = int(match.group(1)) if match else body.get("sku_id")
    if isinstance(sku_id, int) and not isinstance(sku_id, bool):
        # La misma sesión de base de datos que usan los endpoints (los tests la sustituyen).
        sessions = request.app.dependency_overrides.get(get_db, get_db)()
        try:
            sku = next(sessions).get(SKU, sku_id)
            if sku is not None:
                warehouse = body.get("warehouse") if body.get("warehouse") in WAREHOUSES else sku.warehouse
                return SimpleNamespace(sku=sku.sku, client_name=sku.client_name, category=sku.category), warehouse
        finally:
            sessions.close()
    if request.url.path == "/inventory/products":
        return _sku_from_body(body)
    return None


def _capture(request: Request, body: dict, rejection_type: str, rejected_fields: list[str]) -> None:
    user = _user(request)
    if user is None:
        return
    # Caso (a): no hay campos rechazados, pero el cuerpo puede traer el valor que se quería poner.
    quantity = _attempted_quantity(body, rejected_fields or PRODUCT_STOCK_FIELDS)
    resolved = _resolve_sku(request, body)
    if resolved is None:
        inventory = dict.fromkeys(("warehouse", "country", "client_id", "product_id", "product_category"))
        inventory["quantity"] = quantity
    else:
        inventory = telemetry.inventory_properties(resolved[0], resolved[1], quantity)
    telemetry.emit(
        "direct_stock_edit_rejected",
        {
            **inventory,
            "rejection_type": rejection_type,
            "http_method": request.method,
            "api_route": _route_template(request),
            "rejected_fields": rejected_fields,
            "user_role": user["role"],
            # El backoffice manda X-Session-Id en todas sus llamadas; Swagger, curl o un script, no.
            "client_channel": "backoffice_web" if telemetry.current_session_id() else "direct_api",
        },
        user_id=user["id"],
    )


async def capture(request: Request, body: object, rejection_type: str, rejected_fields: list[str]) -> None:
    """Emite el evento sin bloquear el bucle de eventos (TinyDB y la base de datos son síncronas)."""
    try:
        await run_in_threadpool(_capture, request, body if isinstance(body, dict) else {}, rejection_type, rejected_fields)
    except Exception:
        logger.exception("No se pudo capturar direct_stock_edit_rejected")
