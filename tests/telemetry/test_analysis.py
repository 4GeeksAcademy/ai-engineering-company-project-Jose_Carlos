"""Pipeline de análisis de la telemetría (hito 17, Fase 1): services/telemetry/analysis.py.

Cada métrica se prueba contra la tabla telemetry_events del fixture `telemetry_store` (SQLite
en memoria) con eventos guardados por el mismo `record_events` que usa la ingesta real.
"""

import ast
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import event as sa_event

from services import telemetry
from services.telemetry import analysis

START = datetime(2026, 11, 1, tzinfo=timezone.utc)
END = datetime(2026, 11, 8, tzinfo=timezone.utc)

PAGE_VIEW = {"page_route": "/inventory/products", "section": "inventory", "previous_route": None}


def make_event(event_type: str, timestamp: str, properties: dict | None = None, source: str = "backoffice_web"):
    return telemetry.TelemetryEvent(
        eventId=str(uuid.uuid4()),
        timestamp=timestamp,
        sessionId=str(uuid.uuid4()),
        userId=None,
        event_type=event_type,
        schemaVersion="1.0.0",
        requestId=str(uuid.uuid4()),
        source=source,
        environment="test",
        properties=properties if properties is not None else dict(PAGE_VIEW),
    )


def store(*events) -> None:
    telemetry.record_events(list(events))


def page_load(timestamp: str, route: str | None, ttfb: int, lcp: int | None):
    return make_event("page_load_recorded", timestamp, {
        "page_route": route, "device_class": "desktop", "navigation_type": "navigate",
        "ttfb_ms": ttfb, "fcp_ms": ttfb + 100, "lcp_ms": lcp, "inp_ms": None, "cls": 0.0,
    })


def login_ok(timestamp: str, method: str = "password_json"):
    return make_event("user_logged_in", timestamp, {"auth_method": method, "user_role": "user"}, source="api")


def login_ko(timestamp: str, reason: str = "invalid_credentials"):
    return make_event("login_failed", timestamp, {"failure_reason": reason})


@pytest.fixture
def statements(telemetry_store):
    """SQL que llega a la base de datos durante el test."""
    captured: list[str] = []

    def capture(conn, cursor, sql, *rest):
        captured.append(sql)

    sa_event.listen(telemetry_store, "before_cursor_execute", capture)
    yield captured
    sa_event.remove(telemetry_store, "before_cursor_execute", capture)


# =========================================================
# Ventana y tipos
# =========================================================


def test_the_window_is_start_inclusive_end_exclusive():
    store(
        make_event("page_viewed", "2026-10-31T23:59:59.999Z"),  # antes de la ventana
        make_event("page_viewed", "2026-11-01T00:00:00.000Z"),  # justo en start: dentro
        make_event("page_viewed", "2026-11-07T23:59:59.999Z"),
        make_event("page_viewed", "2026-11-08T00:00:00.000Z"),  # justo en end: fuera
    )

    rows = analysis.events_per_day(START, END)

    assert rows == [
        {"date": "2026-11-01", "source": "backoffice_web", "events": 1},
        {"date": "2026-11-07", "source": "backoffice_web", "events": 1},
    ]


def test_events_are_grouped_by_utc_day_not_by_raw_timestamp():
    # Tres instantes distintos del mismo día UTC y uno del día siguiente a 30 min de diferencia.
    store(
        make_event("page_viewed", "2026-11-03T00:10:00.000Z"),
        make_event("page_viewed", "2026-11-03T12:00:00.000Z"),
        make_event("page_viewed", "2026-11-03T23:45:00.000Z"),
        make_event("page_viewed", "2026-11-04T00:15:00.000Z"),
    )

    rows = analysis.events_per_day(START, END)

    assert [(row["date"], row["events"]) for row in rows] == [("2026-11-03", 3), ("2026-11-04", 1)]


def test_events_per_day_splits_by_source():
    store(
        make_event("page_viewed", "2026-11-02T08:00:00.000Z"),
        make_event("page_viewed", "2026-11-02T09:00:00.000Z"),
        login_ok("2026-11-02T08:00:00.000Z"),
    )

    assert analysis.events_per_day(START, END) == [
        {"date": "2026-11-02", "source": "api", "events": 1},
        {"date": "2026-11-02", "source": "backoffice_web", "events": 2},
    ]


@pytest.mark.parametrize("start, end, message", [
    (datetime(2026, 11, 1), END, "zona horaria"),
    (END, START, "anterior"),
    (START, START, "anterior"),
    (START, START + timedelta(days=91), "90"),
])
def test_an_invalid_window_is_rejected_before_querying(start, end, message):
    with pytest.raises(ValueError, match=message):
        analysis.events_per_day(start, end)


# =========================================================
# Métricas
# =========================================================


def test_events_by_type_orders_each_day_by_volume_with_its_share():
    store(
        *[make_event("page_viewed", "2026-11-02T08:00:00.000Z") for _ in range(3)],
        login_ko("2026-11-02T08:00:00.000Z"),
        login_ko("2026-11-03T08:00:00.000Z"),
    )

    assert analysis.events_by_type(START, END) == [
        {"date": "2026-11-02", "event_type": "page_viewed", "events": 3, "share": 0.75},
        {"date": "2026-11-02", "event_type": "login_failed", "events": 1, "share": 0.25},
        {"date": "2026-11-03", "event_type": "login_failed", "events": 1, "share": 1.0},
    ]


def test_error_rate_counts_only_system_errors_over_all_events_of_the_day():
    store(
        *[make_event("page_viewed", "2026-11-02T08:00:00.000Z") for _ in range(6)],
        make_event("api_request_failed", "2026-11-02T09:00:00.000Z", {
            "api_route": "/inventory/products", "http_method": "GET", "failure_kind": "network", "status_code": None,
        }),
        make_event("frontend_error_captured", "2026-11-02T10:00:00.000Z", {
            "page_route": "/inventory", "error_source": "window_error", "error_name": "TypeError",
            "error_fingerprint": "0123456789abcdef", "occurrences": 4,
        }),
        # Rechazo de negocio (sin stock): la API funcionando bien, no un error del sistema.
        make_event("outbound_order_rejected", "2026-11-02T11:00:00.000Z", {}),
        # Un día sin errores no aparece.
        make_event("page_viewed", "2026-11-03T08:00:00.000Z"),
    )

    assert analysis.error_rate_by_type(START, END) == [
        {"date": "2026-11-02", "event_type": "api_request_failed", "errors": 1, "occurrences": 1,
         "total_events": 9, "error_rate": 0.1111},
        {"date": "2026-11-02", "event_type": "frontend_error_captured", "errors": 1, "occurrences": 4,
         "total_events": 9, "error_rate": 0.1111},
    ]


def test_error_rate_without_errors_is_empty():
    store(make_event("page_viewed", "2026-11-02T08:00:00.000Z"))

    assert analysis.error_rate_by_type(START, END) == []


def test_page_load_latency_percentiles_by_day_and_route_dropping_null_routes():
    store(
        *[page_load("2026-11-02T08:00:00.000Z", "/inventory", ttfb, lcp)
          for ttfb, lcp in [(100, 1000), (200, 2000), (300, None), (400, 4000)]],
        page_load("2026-11-02T08:00:00.000Z", None, 9000, 9000),  # sin dimensión: se descarta
        page_load("2026-11-02T08:00:00.000Z", "/incidents", 50, 500),
    )

    rows = analysis.page_load_latency(START, END)

    assert rows == [
        {"date": "2026-11-02", "page_route": "/incidents", "samples": 1, "ttfb_p50_ms": 50.0,
         "ttfb_p95_ms": 50.0, "lcp_p50_ms": 500.0, "lcp_p95_ms": 500.0},
        # lcp nulo no cuenta en sus percentiles; ttfb sí (el evento existe).
        {"date": "2026-11-02", "page_route": "/inventory", "samples": 4, "ttfb_p50_ms": 250.0,
         "ttfb_p95_ms": 385.0, "lcp_p50_ms": 2000.0, "lcp_p95_ms": 3800.0},
    ]


def test_auth_failure_rate_per_day_only_counts_backoffice_logins():
    store(
        login_ko("2026-11-02T08:00:00.000Z"),
        login_ko("2026-11-02T08:01:00.000Z", "network_error"),
        login_ok("2026-11-02T08:02:00.000Z"),
        login_ok("2026-11-02T08:03:00.000Z"),
        login_ok("2026-11-02T08:04:00.000Z", method="oauth2_form"),  # Swagger: fuera del denominador
        login_ok("2026-11-03T08:00:00.000Z"),
        make_event("page_viewed", "2026-11-02T08:00:00.000Z"),
    )

    assert analysis.auth_failure_rate(START, END) == [
        {"date": "2026-11-02", "attempts": 4, "failed": 2, "succeeded": 2, "failure_rate": 0.5},
        {"date": "2026-11-03", "attempts": 1, "failed": 0, "succeeded": 1, "failure_rate": 0.0},
    ]


def test_type_filters_and_window_are_applied_in_sql(statements):
    analysis.auth_failure_rate(START, END)
    analysis.page_load_latency(START, END)

    auth_sql, page_sql = statements
    for sql in (auth_sql, page_sql):
        assert "telemetry_events.timestamp >= ?" in sql and "telemetry_events.timestamp < ?" in sql
    assert "event_type IN" in auth_sql
    assert "event_type IN" in page_sql
    # Nunca SELECT *: solo las columnas que usa la métrica.
    assert "session_id" not in auth_sql and "user_id" not in auth_sql


# =========================================================
# Propiedades de todas las métricas
# =========================================================


def test_every_metric_is_empty_without_data():
    for metric in analysis.METRICS.values():
        assert metric(START, END) == []


def test_every_metric_is_deterministic_and_json_serializable():
    store(
        make_event("page_viewed", "2026-11-02T08:00:00.000Z"),
        page_load("2026-11-02T08:00:00.000Z", "/inventory", 100, None),
        login_ko("2026-11-02T08:00:00.000Z"),
        make_event("api_request_failed", "2026-11-02T09:00:00.000Z", {
            "api_route": "/inventory/products", "http_method": "GET", "failure_kind": "timeout", "status_code": None,
        }),
    )

    for name, metric in analysis.METRICS.items():
        first, second = metric(START, END), metric(START, END)
        assert first == second, name
        assert first, name
        assert all(isinstance(row, dict) and "date" in row for row in first), name
        json.loads(json.dumps(first, allow_nan=False))  # sin NaN ni tipos de numpy


def test_build_report_has_period_and_every_metric():
    store(make_event("page_viewed", "2026-11-02T08:00:00.000Z"))

    report = analysis.build_report(START, END)

    assert report["period"] == {"from": "2026-11-01T00:00:00Z", "to": "2026-11-08T00:00:00Z"}
    assert list(report["metrics"]) == list(analysis.METRICS)
    assert report["metrics"]["events_per_day"] == [{"date": "2026-11-02", "source": "backoffice_web", "events": 1}]


def test_metrics_use_no_loops():
    source = Path(analysis.__file__).read_text(encoding="utf-8")
    loops = [node for node in ast.walk(ast.parse(source)) if isinstance(node, (ast.For, ast.While, ast.AsyncFor))]

    assert loops == []
