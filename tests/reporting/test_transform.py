"""Extracción y transformación del pipeline semanal (hito 19, Fase 1): los cuatro KPIs del BRIEFING."""

import ast
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from data.pipelines.weekly_warehouse_client_performance import config, extract, transform
from tests.reporting.conftest import AS_OF, ENVIRONMENT, PREVIOUS_WEEK, WEEK, inventory_event, store


def run(engine, weeks=(WEEK,), extracted_until=AS_OF):
    events = extract.extract_inventory_events(engine, list(weeks), extracted_until, ENVIRONMENT)
    return transform.transform_weekly_performance(events, list(weeks))


def row(weekly: pd.DataFrame, warehouse: str, client_id: str) -> dict:
    match = weekly[(weekly["warehouse"] == warehouse) & (weekly["client_id"] == client_id)]
    assert len(match) == 1
    return match.iloc[0].to_dict()


def test_the_four_kpis_follow_the_briefing_definitions(week_of_activity):
    result = run(week_of_activity)
    weekly = result.weekly

    assert list(weekly.columns) == [*config.KEY_COLUMNS, *config.KPI_COLUMNS]
    assert len(weekly) == 3
    la = row(weekly, "los_angeles", "purestep_footwear")
    assert la["week_start"] == WEEK
    assert la["inbound_units_count"] == 420       # suma de quantity, no conteo de entradas
    assert la["outbound_orders_count"] == 4        # conteo de despachos
    assert la["stockout_events_count"] == 1
    assert la["discrepancy_events_count"] == 1
    assert la["discrepancy_rate"] == 0.25          # 1 / 4

    glowlab = row(weekly, "los_angeles", "glowlab_cosmetics")
    assert (glowlab["inbound_units_count"], glowlab["outbound_orders_count"]) == (80, 2)
    assert glowlab["discrepancy_rate"] == 0.0


def test_discrepancy_rate_is_zero_without_outbound_orders(week_of_activity):
    zaragoza = row(run(week_of_activity).weekly, "zaragoza", "purestep_footwear")
    assert zaragoza["outbound_orders_count"] == 0
    assert zaragoza["discrepancy_events_count"] == 1
    assert zaragoza["discrepancy_rate"] == 0.0


def test_a_row_never_mixes_clients(week_of_activity):
    weekly = run(week_of_activity).weekly
    assert not weekly.duplicated(subset=list(config.KEY_COLUMNS)).any()
    assert set(weekly["client_id"]) == {"purestep_footwear", "glowlab_cosmetics"}


def test_weeks_are_iso_weeks_in_utc(reporting_db):
    store(
        reporting_db,
        inventory_event("outbound_order_created", "2026-11-01T23:59:59.999Z"),  # domingo → semana anterior
        inventory_event("outbound_order_created", "2026-11-02T00:00:00.000Z"),  # lunes 00:00 → esta semana
        inventory_event("outbound_order_created", "2026-11-08T23:59:59.999Z"),  # domingo, último instante
    )
    weekly = run(reporting_db, weeks=(PREVIOUS_WEEK, WEEK)).weekly
    counts = dict(zip(weekly["week_start"], weekly["outbound_orders_count"]))
    assert counts == {PREVIOUS_WEEK: 1, WEEK: 2}


def test_same_movement_with_two_event_ids_counts_once(reporting_db):
    store(
        reporting_db,
        inventory_event("outbound_order_created", "2026-11-03T12:00:00.000Z", business_id=7001),
        inventory_event("outbound_order_created", "2026-11-03T12:00:02.000Z", business_id=7001),
        inventory_event("outbound_order_created", "2026-11-03T12:05:00.000Z", business_id=7002),
    )
    result = run(reporting_db)
    assert result.weekly.iloc[0]["outbound_orders_count"] == 2
    assert result.events_deduplicated == 1


def test_extraction_filters_types_environment_window_and_ingestion_cut(reporting_db):
    store(
        reporting_db,
        inventory_event("outbound_order_created", "2026-11-03T12:00:00.000Z"),
        inventory_event("outbound_order_created", "2026-11-03T12:00:00.000Z", environment="development"),
        inventory_event("outbound_order_created", "2026-11-10T12:00:00.000Z"),  # semana siguiente
    )
    # Ingerido después del corte de la corrida: entra en la siguiente, no en esta.
    store(reporting_db, inventory_event("outbound_order_created", "2026-11-04T12:00:00.000Z"),
          ingested_at=datetime(2026, 11, 9, 7, 0, tzinfo=timezone.utc))
    events = extract.extract_inventory_events(reporting_db, [WEEK], AS_OF, ENVIRONMENT)
    assert len(events) == 1
    assert list(events.columns) == extract.EVENT_COLUMNS
    assert events.iloc[0]["warehouse"] == "los_angeles"
    assert events.iloc[0]["business_key"] is not None


def test_invalid_rows_are_discarded_and_counted():
    events = pd.DataFrame([
        {"event_id": "a", "event_type": config.INBOUND_EVENT, "timestamp": "2026-11-03T10:00:00Z", "created_at": None,
         "warehouse": "madrid", "client_id": "x", "quantity": 5, "business_key": "1"},
        {"event_id": "b", "event_type": config.INBOUND_EVENT, "timestamp": "2026-11-03T10:00:00Z", "created_at": None,
         "warehouse": "zaragoza", "client_id": None, "quantity": 5, "business_key": "2"},
        {"event_id": "c", "event_type": config.INBOUND_EVENT, "timestamp": "2026-11-03T10:00:00Z", "created_at": None,
         "warehouse": "zaragoza", "client_id": "ok", "quantity": 5, "business_key": "3"},
    ])
    result = transform.transform_weekly_performance(events, [WEEK])
    assert result.events_discarded == 2
    assert result.weekly.iloc[0]["inbound_units_count"] == 5


def test_no_events_gives_an_empty_frame(reporting_db):
    result = run(reporting_db)
    assert result.weekly.empty
    assert list(result.weekly.columns) == transform.WEEKLY_COLUMNS


def test_resolve_weeks_defaults_to_last_closed_week_plus_lookback(reporting_db):
    weeks = extract.resolve_weeks(reporting_db, as_of=AS_OF, extracted_until=AS_OF, environment=ENVIRONMENT,
                                  include_late_arrivals=False)
    assert weeks == [PREVIOUS_WEEK, WEEK]


def test_resolve_weeks_rejects_a_week_start_that_is_not_monday(reporting_db):
    with pytest.raises(ValueError):
        extract.resolve_weeks(reporting_db, as_of=AS_OF, extracted_until=AS_OF, environment=ENVIRONMENT,
                              week_start=datetime(2026, 11, 3).date())


def test_transform_uses_no_loops():
    tree = ast.parse(Path(transform.__file__).read_text(encoding="utf-8"))
    assert not [node for node in ast.walk(tree) if isinstance(node, (ast.For, ast.While))]
