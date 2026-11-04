"""Plan de Telemetría (CONTEXT-10): event-schemas.json es un JSON Schema draft-07 válido,
cumple las reglas del plan y coincide con TELEMETRY_PLAN.md y con el código de inventario."""

import copy
import json
import re
from pathlib import Path

import pytest
from jsonschema import Draft7Validator, FormatChecker

from services.api.user_models import UserRole
from services.models import CATEGORIES, EXIT_TYPES, WAREHOUSES


ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = json.loads((ROOT / "event-schemas.json").read_text(encoding="utf-8"))
PLAN = (ROOT / "TELEMETRY_PLAN.md").read_text(encoding="utf-8")

DEFINITIONS = SCHEMAS["definitions"]
EVENTS = {name: schema for name, schema in DEFINITIONS.items() if name != "envelope"}
VALIDATOR = Draft7Validator(SCHEMAS, format_checker=FormatChecker())

# CONTEXT-10 §3: métricas obligatorias y campos mínimos de los eventos de inventario.
MANDATORY = {
    "inbound_order_created",
    "outbound_order_created",
    "stock_threshold_triggered",
    "direct_stock_edit_rejected",
    "inventory_discrepancy_detected",
}
INVENTORY_FIELDS = {"warehouse", "client_id", "product_id", "product_category", "quantity"}
ENVELOPE_FIELDS = {"eventId", "timestamp", "sessionId", "userId", "event_type", "schemaVersion", "requestId", "properties"}

# Datos que nunca pueden aparecer en una allowlist (sección 4.7 del plan).
FORBIDDEN_KEYS = {"tracking_number", "email", "reference", "name", "ip", "recipient", "address", "carrier", "message", "stack"}


def allowlist(event_type: str) -> dict:
    """Propiedades permitidas de un evento: {nombre: esquema}."""
    return EVENTS[event_type]["properties"]["properties"]["properties"]


def outbound_event(**overrides) -> dict:
    event = {
        "eventId": "3f2b8c1e-7a4d-4e9b-9c2f-1d5e6a7b8c90",
        "timestamp": "2026-10-24T09:15:02.481Z",
        "sessionId": "9a1c3e5f-2b4d-4f6a-8c0e-1a3b5c7d9e2f",
        "userId": "5d0f7a52-8a0c-4b8e-9f3e-2c1d4b6a8e10",
        "event_type": "outbound_order_created",
        "schemaVersion": "1.0.0",
        "requestId": "c4e6a8b0-1d3f-4a5b-8c7d-9e0f1a2b3c4d",
        "source": "backoffice_web",
        "environment": "production",
        "properties": {
            "warehouse": "los_angeles",
            "country": "US",
            "client_id": "soundwave_electronics",
            "product_id": "TEC-EAR-001",
            "product_category": "electronics",
            "quantity": 2,
            "outbound_order_id": 41,
            "stock_after": 46,
        },
    }
    event.update(overrides)
    return event


# =========================================================
# El archivo es un JSON Schema draft-07 válido
# =========================================================


def test_event_schemas_is_a_valid_draft_07_schema():
    assert SCHEMAS["$schema"] == "http://json-schema.org/draft-07/schema#"
    Draft7Validator.check_schema(SCHEMAS)


def test_every_event_is_reachable_from_the_root_one_of():
    refs = {item["$ref"].removeprefix("#/definitions/") for item in SCHEMAS["oneOf"]}
    assert refs == set(EVENTS)


# =========================================================
# Event Envelope
# =========================================================


def test_envelope_requires_the_standard_fields_and_nothing_else_at_top_level():
    envelope = DEFINITIONS["envelope"]
    assert ENVELOPE_FIELDS <= set(envelope["required"])
    assert set(envelope["required"]) == set(envelope["properties"])
    assert envelope["additionalProperties"] is False


def test_the_plan_example_is_a_valid_event():
    assert list(VALIDATOR.iter_errors(outbound_event())) == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"timestamp": "2026-10-24 09:15:02"},  # no es ISO 8601 UTC
        {"eventId": "not-a-uuid"},
        {"event_type": "OutboundOrderCreated"},  # no sigue entidad_acción
        {"schemaVersion": "1"},
        {"userId": "admin@trackflow.com"},  # nunca el email
        {"extra": "x"},  # nada fuera del envelope
    ],
)
def test_envelope_rejects_malformed_events(overrides):
    assert not VALIDATOR.is_valid(outbound_event(**overrides))


def test_envelope_keys_are_always_present_even_when_null():
    event = outbound_event()
    del event["sessionId"]
    assert not VALIDATOR.is_valid(event)
    assert VALIDATOR.is_valid(outbound_event(sessionId=None))


# =========================================================
# Allowlists
# =========================================================


@pytest.mark.parametrize("event_type", sorted(EVENTS))
def test_every_event_has_a_closed_allowlist(event_type):
    payload = EVENTS[event_type]["properties"]["properties"]
    assert payload["additionalProperties"] is False
    assert set(payload["required"]) <= set(payload["properties"])
    for name, spec in payload["properties"].items():
        assert spec.get("description"), f"{event_type}.{name} sin descripción"
        assert "type" in spec or "const" in spec, f"{event_type}.{name} sin tipo"
        assert name not in FORBIDDEN_KEYS, f"{event_type}.{name} está prohibido"


def test_properties_outside_the_allowlist_are_rejected():
    event = outbound_event()
    event["properties"]["tracking_number"] = "1Z999AA10123456784"
    assert not VALIDATOR.is_valid(event)


def test_a_missing_required_property_is_rejected():
    event = outbound_event()
    del event["properties"]["client_id"]
    assert not VALIDATOR.is_valid(event)


# =========================================================
# Catálogo: obligatorios, oportunidades y taxonomía
# =========================================================


def test_all_mandatory_metrics_are_present_and_classified_as_mandatory():
    mandatory = {name for name, schema in EVENTS.items() if schema["x-classification"] == "mandatory"}
    assert mandatory == MANDATORY


def test_mandatory_inventory_events_carry_the_minimum_briefing_fields():
    for event_type in MANDATORY:
        assert INVENTORY_FIELDS <= set(allowlist(event_type)), event_type


def test_at_least_eight_opportunities_across_three_categories():
    opportunities = [schema for schema in EVENTS.values() if schema["x-classification"] == "opportunity"]
    assert len(opportunities) >= 8
    assert len({schema["x-category"] for schema in opportunities}) >= 3


@pytest.mark.parametrize("event_type", sorted(EVENTS))
def test_event_metadata_is_complete(event_type):
    schema = EVENTS[event_type]
    assert re.fullmatch(r"[a-z]+(_[a-z]+)+", event_type)
    assert schema["properties"]["event_type"] == {"const": event_type}
    assert schema["x-hypothesis"] and schema["x-decision"] and schema["x-trigger"]
    assert schema["x-delivery"]["mode"] in {"stream", "batch"}
    assert schema["x-delivery"]["justification"]
    pii = schema["x-pii"]
    assert isinstance(pii["containsPii"], bool) and pii["treatment"]
    assert set(pii["fields"]) <= set(allowlist(event_type))
    assert bool(pii["fields"]) == pii["containsPii"]


# =========================================================
# Coherencia con el código de inventario
# =========================================================


def test_enums_match_the_inventory_and_auth_models():
    spec = allowlist("inbound_order_created")
    assert spec["product_category"]["enum"] == list(CATEGORIES)
    # Un nombre de telemetría por cada código interno de almacén (LA, ZGZ).
    assert len(spec["warehouse"]["enum"]) == len(WAREHOUSES)
    assert set(allowlist("stock_threshold_triggered")["trigger_order_type"]["enum"]) == set(EXIT_TYPES)
    assert set(allowlist("direct_stock_edit_rejected")["user_role"]["enum"]) == {role.value for role in UserRole}


# =========================================================
# Coherencia con TELEMETRY_PLAN.md
# =========================================================


def test_plan_and_json_list_the_same_events():
    in_plan = set(re.findall(r"^#### \d+\. `([a-z_]+)`$", PLAN, flags=re.MULTILINE))
    assert in_plan == set(EVENTS)


def test_plan_delivery_table_matches_the_json():
    rows = dict(re.findall(r"^\| `([a-z_]+)` \| \*\*(stream|batch)\*\* \|", PLAN, flags=re.MULTILINE))
    assert rows == {name: schema["x-delivery"]["mode"] for name, schema in EVENTS.items()}


def test_examples_built_from_the_plan_mappings_validate():
    # Zaragoza → ES, slug de "GlowLab Cosmetics" (sección 4.3 del plan).
    event = copy.deepcopy(outbound_event())
    event["properties"].update(
        warehouse="zaragoza", country="ES", client_id="glowlab_cosmetics", product_id="CSM-SRM-030", product_category="cosmetics"
    )
    assert VALIDATOR.is_valid(event)
