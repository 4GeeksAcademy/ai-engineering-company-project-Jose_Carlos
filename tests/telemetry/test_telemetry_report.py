"""GET /telemetry/report (hito 17, Fase 2): periodo por defecto de 7 días, parámetros ISO 8601,
estructura {"period", "metrics"} y caché en memoria de 60 s que evita recalcular."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import OperationalError

from services import telemetry
from services.api import cache
from services.routers import telemetry as telemetry_router
from services.telemetry import analysis

URL = "/telemetry/report"


def page_viewed(timestamp: str):
    return telemetry.TelemetryEvent(
        eventId=str(uuid.uuid4()), timestamp=timestamp, sessionId=None, userId=None, event_type="page_viewed",
        schemaVersion="1.0.0", requestId=str(uuid.uuid4()), source="backoffice_web", environment="test",
        properties={"page_route": "/inventory", "section": "inventory", "previous_route": None},
    )


@pytest.fixture
def report_calls(monkeypatch):
    """Ventanas con las que el endpoint ha llamado al pipeline (cada llamada es un cálculo)."""
    calls: list[tuple[datetime, datetime]] = []
    real = analysis.build_report

    def spy(start, end, session=None):
        calls.append((start, end))
        return real(start, end, session)

    monkeypatch.setattr(analysis, "build_report", spy)
    return calls


@pytest.fixture
def clock(monkeypatch):
    now = {"t": 1000.0}
    monkeypatch.setattr(cache, "_clock", lambda: now["t"])
    return now


def test_requires_a_session(anon_client):
    assert anon_client.get(URL).status_code == 401


def test_report_structure_with_explicit_period(client):
    telemetry.record_events([page_viewed("2026-11-02T08:00:00.000Z"), page_viewed("2026-11-09T08:00:00.000Z")])

    response = client.get(URL, params={"start_date": "2026-11-01T00:00:00Z", "end_date": "2026-11-08T00:00:00Z"})

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"period", "metrics"}
    assert body["period"] == {"from": "2026-11-01T00:00:00Z", "to": "2026-11-08T00:00:00Z"}
    assert set(body["metrics"]) >= {"events_per_day", "error_rate_by_type", "auth_failure_rate"}
    assert list(body["metrics"]) == list(analysis.METRICS)
    # El evento del día 9 queda fuera: la ventana se aplicó en SQL.
    assert body["metrics"]["events_per_day"] == [{"date": "2026-11-02", "source": "backoffice_web", "events": 1}]


def test_default_period_is_the_last_seven_days_in_utc(client, report_calls):
    before = datetime.now(timezone.utc)
    body = client.get(URL).json()
    after = datetime.now(timezone.utc)

    start, end = report_calls[0]
    assert end - start == timedelta(days=7)
    assert before <= end <= after
    assert start.tzinfo == timezone.utc and end.tzinfo == timezone.utc
    assert body["period"]["to"].endswith("Z")


def test_only_end_date_uses_seven_days_before_it(client, report_calls):
    client.get(URL, params={"end_date": "2026-11-08T00:00:00Z"})

    assert report_calls == [(datetime(2026, 11, 1, tzinfo=timezone.utc), datetime(2026, 11, 8, tzinfo=timezone.utc))]


def test_dates_without_zone_are_utc_and_offsets_are_converted(client, report_calls):
    client.get(URL, params={"start_date": "2026-11-01T00:00:00", "end_date": "2026-11-08T02:00:00+02:00"})

    assert report_calls == [(datetime(2026, 11, 1, tzinfo=timezone.utc), datetime(2026, 11, 8, tzinfo=timezone.utc))]


@pytest.mark.parametrize("params", [
    {"start_date": "2026-11-08T00:00:00Z", "end_date": "2026-11-01T00:00:00Z"},  # al revés
    {"start_date": "2026-01-01T00:00:00Z", "end_date": "2026-11-01T00:00:00Z"},  # más de 90 días
    {"start_date": "ayer"},                                                       # no es ISO 8601
])
def test_invalid_periods_are_422(client, params, report_calls):
    assert client.get(URL, params=params).status_code == 422
    assert report_calls == []


# =========================================================
# Caché
# =========================================================


def test_same_period_within_ttl_is_served_from_cache(client, report_calls, clock):
    params = {"start_date": "2026-11-01T00:00:00Z", "end_date": "2026-11-08T00:00:00Z"}
    first = client.get(URL, params=params).json()

    telemetry.record_events([page_viewed("2026-11-02T08:00:00.000Z")])
    clock["t"] += 59
    second = client.get(URL, params=params).json()

    assert len(report_calls) == 1
    assert second == first  # el evento nuevo aún no se ve: es la respuesta cacheada

    clock["t"] += 2  # pasan los 60 s
    third = client.get(URL, params=params).json()

    assert len(report_calls) == 2
    assert third["metrics"]["events_per_day"] == [{"date": "2026-11-02", "source": "backoffice_web", "events": 1}]


def test_the_default_period_is_also_cached(client, report_calls, clock):
    first = client.get(URL).json()
    clock["t"] += 30
    second = client.get(URL).json()

    assert len(report_calls) == 1
    assert second["period"] == first["period"]


def test_equivalent_dates_share_the_cache_entry_and_different_ones_do_not(client, report_calls, clock):
    client.get(URL, params={"start_date": "2026-11-01T00:00:00Z", "end_date": "2026-11-08T00:00:00Z"})
    client.get(URL, params={"start_date": "2026-11-01T01:00:00+01:00", "end_date": "2026-11-08T00:00:00"})
    assert len(report_calls) == 1

    client.get(URL, params={"start_date": "2026-11-02T00:00:00Z", "end_date": "2026-11-08T00:00:00Z"})
    assert len(report_calls) == 2


def test_storage_failure_is_503_and_is_not_cached(client, monkeypatch, clock):
    def broken(start, end, session=None):
        raise OperationalError("SELECT", {}, Exception("connection refused"))

    real = analysis.build_report
    monkeypatch.setattr(analysis, "build_report", broken)
    assert client.get(URL).status_code == 503

    # Mismo periodo, dentro del TTL: el error no se guardó, así que se vuelve a calcular.
    monkeypatch.setattr(analysis, "build_report", real)
    assert client.get(URL).status_code == 200


def test_the_endpoint_does_not_compute_metrics_itself():
    # El cálculo vive en el pipeline: el router no usa Pandas ni consulta la tabla.
    source = telemetry_router.__file__
    text = open(source, encoding="utf-8").read()

    assert "pandas" not in text and "groupby" not in text and "select(" not in text
