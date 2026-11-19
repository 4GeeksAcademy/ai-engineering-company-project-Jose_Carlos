"""Idempotencia de la carga y log de ejecución (hito 19, Fase 3; PIPELINE_DESIGN.md §8 y §9)."""

import uuid
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import pytest
from sqlalchemy import insert, select
from sqlalchemy.exc import OperationalError

from data.pipelines import pipeline
from data.pipelines.weekly_warehouse_client_performance import config, load, run_log
from data.pipelines.weekly_warehouse_client_performance.schema import pipeline_runs as RUNS
from data.pipelines.weekly_warehouse_client_performance.schema import weekly_warehouse_client_performance as TARGET
from tests.reporting.conftest import AS_OF, PREVIOUS_WEEK, WEEK, inventory_event, store

pytestmark = pytest.mark.usefixtures("prefect_server")

KPIS = ["warehouse", "client_id", "week_start", *config.KPI_COLUMNS]


def run_flow(**parameters):
    parameters.setdefault("as_of", AS_OF)
    parameters.setdefault("lookback_weeks", 0)
    return pipeline.weekly_warehouse_client_performance_flow(**parameters)


def table(engine, columns=("id", *KPIS)) -> list[tuple]:
    with engine.connect() as connection:
        rows = connection.execute(
            select(*(TARGET.c[name] for name in columns)).order_by(TARGET.c.week_start, TARGET.c.warehouse, TARGET.c.client_id)
        )
        return [tuple(row) for row in rows]


def runs(engine) -> list[dict]:
    with engine.connect() as connection:
        return [dict(row._mapping) for row in connection.execute(select(RUNS).order_by(RUNS.c.started_at))]


@pytest.fixture
def no_retry_delay(monkeypatch):
    for name in ("load_weekly_performance", "start_pipeline_run"):
        monkeypatch.setattr(pipeline, name, getattr(pipeline, name).with_options(retry_delay_seconds=0))


# =========================================================
# Idempotencia de la carga
# =========================================================


def test_running_twice_over_the_same_data_leaves_the_table_identical(week_of_activity):
    run_flow()
    first = table(week_of_activity)
    run_flow(as_of=AS_OF + timedelta(minutes=30))
    second = table(week_of_activity)

    assert len(first) == 3
    assert second == first        # mismas filas, mismos valores y mismos ids: nada duplicado


def test_loading_the_same_frame_twice_is_a_no_op_except_computed_at(week_of_activity):
    weekly = pd.DataFrame([{
        "warehouse": "zaragoza", "client_id": "purestep_footwear", "week_start": WEEK,
        "inbound_units_count": 10, "outbound_orders_count": 4, "stockout_events_count": 1,
        "discrepancy_events_count": 1, "discrepancy_rate": 0.25,
    }])
    first = load.load_weekly_performance(week_of_activity, weekly, [WEEK], AS_OF)
    before = table(week_of_activity)
    second = load.load_weekly_performance(week_of_activity, weekly, [WEEK], AS_OF + timedelta(hours=1))
    assert first == second == load.LoadResult(rows_upserted=1, rows_deleted=0)
    assert table(week_of_activity) == before


def test_a_load_that_fails_midway_leaves_the_table_as_it_was_and_the_rerun_completes_it(
    week_of_activity, monkeypatch, no_retry_delay
):
    run_flow()                                   # corrida correcta: estado inicial conocido
    expected = table(week_of_activity, KPIS)
    # Nuevos eventos de la misma semana: la siguiente corrida tiene que actualizar filas.
    store(week_of_activity, inventory_event("outbound_order_created", "2026-11-06T09:00:00.000Z"),
          ingested_at=AS_OF + timedelta(minutes=1))
    original = load.upsert_rows

    def upsert_then_lose_connection(connection, weekly, computed_at):
        original(connection, weekly, computed_at)            # el UPSERT llega a ejecutarse…
        raise OperationalError("COMMIT", {}, Exception("server closed the connection"))  # …y se corta

    monkeypatch.setattr(load, "upsert_rows", upsert_then_lose_connection)
    with pytest.raises(pipeline.PipelineStageError):
        run_flow(as_of=AS_OF + timedelta(hours=1))
    assert table(week_of_activity, KPIS) == expected     # ROLLBACK: ni una fila a medias

    failed = runs(week_of_activity)[-1]
    assert (failed["status"], failed["error_stage"]) == ("failed", "load")
    assert "server closed the connection" in failed["error_message"]

    monkeypatch.setattr(load, "upsert_rows", original)
    run_flow(as_of=AS_OF + timedelta(hours=2))            # segunda corrida tras el fallo
    after = {(r[0], r[1]): r for r in table(week_of_activity, KPIS)}
    assert len(after) == 3                                 # sin duplicados
    assert after[("los_angeles", "purestep_footwear")][4] == 5   # 4 despachos + el nuevo


def test_rows_that_the_calculation_no_longer_produces_are_removed_for_the_processed_weeks(week_of_activity):
    with week_of_activity.begin() as connection:
        connection.execute(insert(TARGET), [
            {"id": uuid.uuid4(), "warehouse": "zaragoza", "client_id": "ghost_brand", "week_start": WEEK,
             "computed_at": AS_OF},
            {"id": uuid.uuid4(), "warehouse": "zaragoza", "client_id": "ghost_brand", "week_start": PREVIOUS_WEEK,
             "computed_at": AS_OF},
        ])
    summary = run_flow()
    assert summary["rows_deleted"] == 1
    clients = {(row[3], row[2]) for row in table(week_of_activity)}
    assert (WEEK, "ghost_brand") not in clients
    assert (PREVIOUS_WEEK, "ghost_brand") in clients       # semana no procesada: intacta


# =========================================================
# Log de ejecución
# =========================================================


def test_each_run_records_start_end_counts_status_and_errors(week_of_activity):
    summary = run_flow()
    [run] = runs(week_of_activity)

    assert str(run["run_id"]) == summary["run_id"]
    assert run["pipeline_name"] == config.PIPELINE_NAME
    assert (run["status"], run["trigger"]) == ("completed", "scheduled")
    assert run["started_at"] is not None and run["finished_at"] >= run["started_at"]
    assert run["weeks_processed"] == [WEEK.isoformat()]
    assert (run["events_extracted"], run["rows_upserted"], run["rows_deleted"]) == (13, 3, 0)
    assert (run["events_discarded"], run["events_deduplicated"]) == (0, 0)
    assert run["error_stage"] is None and run["error_message"] is None
    assert run["parameters"]["lookback_weeks"] == 0
    assert run["source_watermark"].replace(tzinfo=timezone.utc) == AS_OF


def test_late_arrivals_after_the_watermark_are_recalculated_by_the_next_run(week_of_activity):
    run_flow()
    # Un despacho de la semana anterior que llega una hora después de la corrida.
    store(week_of_activity, inventory_event("outbound_order_created", "2026-10-30T18:00:00.000Z"),
          ingested_at=AS_OF + timedelta(hours=1))

    summary = run_flow(as_of=AS_OF + timedelta(days=1))
    assert summary["weeks_processed"] == [PREVIOUS_WEEK.isoformat(), WEEK.isoformat()]
    late = [row for row in table(week_of_activity, KPIS) if row[2] == PREVIOUS_WEEK]
    assert late == [("los_angeles", "purestep_footwear", PREVIOUS_WEEK, 0, 1, 0, 0, 0.0)]


def test_a_second_concurrent_run_is_rejected_without_touching_the_first(week_of_activity, no_retry_delay):
    other = uuid.uuid4()
    run_log.start_run(week_of_activity, run_id=other, pipeline_name=config.PIPELINE_NAME, trigger="manual",
                      triggered_by=None, started_at=config.utc_now(), source_watermark=AS_OF, parameters={},
                      code_version=None)
    with pytest.raises(pipeline.PipelineStageError) as error:
        run_flow()
    assert error.value.stage == "start"
    assert [r["status"] for r in runs(week_of_activity)] == ["running"]
    assert table(week_of_activity) == []


def test_a_run_left_running_by_a_dead_process_is_marked_crashed_by_the_next_one(week_of_activity):
    stale = uuid.uuid4()
    run_log.start_run(week_of_activity, run_id=stale, pipeline_name=config.PIPELINE_NAME, trigger="scheduled",
                      triggered_by=None, started_at=config.utc_now() - timedelta(hours=3), source_watermark=AS_OF,
                      parameters={}, code_version=None)
    run_flow()
    by_id = {r["run_id"]: r for r in runs(week_of_activity)}
    assert (by_id[stale]["status"], by_id[stale]["error_stage"]) == ("failed", "crashed")
    assert sum(r["status"] == "completed" for r in by_id.values()) == 1


def test_the_failed_run_does_not_move_the_watermark(week_of_activity, monkeypatch, no_retry_delay):
    run_flow()
    good = run_log.last_successful_watermark(week_of_activity, config.PIPELINE_NAME)
    monkeypatch.setattr(load, "load_weekly_performance",
                        lambda *a, **k: (_ for _ in ()).throw(OperationalError("x", {}, Exception("down"))))
    with pytest.raises(pipeline.PipelineStageError):
        run_flow(as_of=AS_OF + timedelta(hours=1))
    assert run_log.last_successful_watermark(week_of_activity, config.PIPELINE_NAME) == good


def test_get_latest_run_serializes_for_the_status_endpoint(week_of_activity):
    summary = run_flow()
    latest = run_log.get_latest_run(week_of_activity)
    assert latest["pipeline_name"] == config.PIPELINE_NAME
    assert latest["latest_successful_run_id"] == summary["run_id"]
    run = latest["latest_run"]
    assert run["status"] == "completed"
    assert run["started_at"].endswith("Z") and run["finished_at"].endswith("Z")
    assert run["source_watermark"] == "2026-11-09T06:00:00Z"
    assert run_log.get_latest_run(week_of_activity, "otro_pipeline") is None
