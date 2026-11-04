"""Contrato entre el TelemetryService del backoffice y event-schemas.json (hito 15).

El navegador saca `schemaVersion` de la constante de uis/backoffice/app/lib/telemetry-schema.ts:
si un esquema cambia de versión y la constante no, los eventos llegarían con una versión que no
existe. Además se comprueba que la telemetría solo sale por el servicio y que la URL no está
escrita a mano en ningún sitio.
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKOFFICE = ROOT / "uis" / "backoffice"
SCHEMA_TS = BACKOFFICE / "app" / "lib" / "telemetry-schema.ts"
SERVICE_TS = BACKOFFICE / "app" / "lib" / "telemetry.ts"
EVENTS = json.loads((ROOT / "event-schemas.json").read_text(encoding="utf-8"))["definitions"]


def ts_versions() -> dict[str, str]:
    body = SCHEMA_TS.read_text(encoding="utf-8").split("TELEMETRY_SCHEMA_VERSIONS = {", 1)[1].split("}", 1)[0]
    return dict(re.findall(r"^\s*([a-z_]+): \"(\d+\.\d+\.\d+)\",", body, flags=re.MULTILINE))


def frontend_sources() -> list[Path]:
    files = [*BACKOFFICE.glob("app/**/*.ts"), *BACKOFFICE.glob("app/**/*.tsx"), BACKOFFICE / "instrumentation-client.ts"]
    return [path for path in files if path.exists()]


def test_every_browser_event_uses_the_schema_version_of_event_schemas_json():
    versions = ts_versions()

    assert versions
    for event_type, version in versions.items():
        assert EVENTS[event_type]["properties"]["schemaVersion"]["const"] == version, event_type


def test_the_browser_only_tracks_events_whose_schema_says_backoffice_web():
    for event_type in ts_versions():
        assert EVENTS[event_type]["properties"]["source"]["const"] == "backoffice_web", event_type


def test_every_implemented_browser_event_is_in_the_constant():
    implemented = {
        name for name, schema in EVENTS.items()
        if name != "envelope" and schema["x-implemented"] and schema["properties"]["source"]["const"] == "backoffice_web"
    }

    assert implemented == set(ts_versions())


def test_the_fourteen_events_of_hito_15_are_marked_as_implemented():
    implemented = {name for name, schema in EVENTS.items() if name != "envelope" and schema["x-implemented"]}

    assert len(implemented) == 14
    assert {name for name, schema in EVENTS.items() if schema.get("x-classification") == "mandatory"} <= implemented


def test_the_telemetry_url_comes_from_the_environment_and_is_never_hardcoded():
    assert "process.env.NEXT_PUBLIC_TELEMETRY_ENDPOINT" in SERVICE_TS.read_text(encoding="utf-8")
    for path in frontend_sources():
        assert "/telemetry/events" not in path.read_text(encoding="utf-8"), path


def test_only_the_telemetry_service_sends_telemetry():
    for path in frontend_sources():
        if path == SERVICE_TS:
            continue
        source = path.read_text(encoding="utf-8")
        assert "sendBeacon" not in source, path
        assert "NEXT_PUBLIC_TELEMETRY_ENDPOINT" not in source, path


def test_the_telemetry_service_only_reads_the_status_code_of_the_ingestion_response():
    # Hito 16: la respuesta pasa de {"received"} a {"received", "stored", "rejected"}. Es
    # transparente porque el TelemetryService decide solo con response.status (reintenta 5xx y
    # 429, descarta el resto) y nunca lee el cuerpo.
    source = SERVICE_TS.read_text(encoding="utf-8")

    assert "response.status >= 500 || response.status === 429" in source
    assert not re.search(r"response\.(json|text|body|blob|arrayBuffer)\b", source)
