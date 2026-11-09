"""El flow de Prefect de punta a punta (hito 19): data/pipelines/pipeline.py.

Corre contra un servidor de Prefect temporal (`prefect_test_harness`) y el SQLite de
`reporting_db`. Las cifras esperadas son las de `week_of_activity` (ver conftest).
"""

import json
from pathlib import Path

import pytest
from prefect.testing.utilities import prefect_test_harness
from sqlalchemy import select

from data.pipelines import pipeline
from data.pipelines.weekly_warehouse_client_performance import quality
from data.pipelines.weekly_warehouse_client_performance.schema import weekly_warehouse_client_performance as TARGET
from tests.reporting.conftest import AS_OF, WEEK


@pytest.fixture(scope="module", autouse=True)
def prefect_server():
    with prefect_test_harness(server_startup_timeout=120):
        yield


def target_rows(engine) -> list[dict]:
    with engine.connect() as connection:
        rows = connection.execute(select(TARGET).order_by(TARGET.c.week_start, TARGET.c.warehouse, TARGET.c.client_id))
        return [dict(row._mapping) for row in rows]


def run_flow(**parameters):
    parameters.setdefault("as_of", AS_OF)
    parameters.setdefault("lookback_weeks", 0)
    return pipeline.weekly_warehouse_client_performance_flow(**parameters)


def test_the_flow_extracts_transforms_and_loads_the_briefing_table(week_of_activity):
    summary = run_flow()

    assert summary["weeks_processed"] == [WEEK.isoformat()]
    assert summary["events_extracted"] == 13
    assert summary["rows_upserted"] == 3
    rows = target_rows(week_of_activity)
    assert [(r["warehouse"], r["client_id"]) for r in rows] == [
        ("los_angeles", "glowlab_cosmetics"), ("los_angeles", "purestep_footwear"), ("zaragoza", "purestep_footwear"),
    ]
    la = rows[1]
    assert (la["inbound_units_count"], la["outbound_orders_count"], la["stockout_events_count"],
            la["discrepancy_events_count"], la["discrepancy_rate"]) == (420, 4, 1, 1, 0.25)


def test_optional_snapshot_is_written_with_the_endpoint_contract(week_of_activity, tmp_path):
    run_flow()
    snapshot = json.loads((tmp_path / "snapshots" / f"week_start={WEEK.isoformat()}.json").read_text(encoding="utf-8"))
    assert snapshot["week_start"] == WEEK.isoformat()
    assert {entry["client_id"] for entry in snapshot["entries"]} == {"purestep_footwear", "glowlab_cosmetics"}
    assert set(snapshot["entries"][0]) == {
        "warehouse", "client_id", "inbound_units_count", "outbound_orders_count",
        "stockout_events_count", "discrepancy_events_count", "discrepancy_rate",
    }


def test_a_failing_optional_task_does_not_stop_the_run(week_of_activity, monkeypatch):
    def broken(*args, **kwargs):
        raise OSError("disco lleno")

    monkeypatch.setattr(quality, "export_weekly_snapshot", broken)
    summary = run_flow()

    assert summary["rows_upserted"] == 3                       # la carga se hizo igualmente
    assert len(target_rows(week_of_activity)) == 3
    failures = [w for w in summary["warnings"] if w["step"] == "export_weekly_snapshot"]
    assert failures and "disco lleno" in failures[0]["error"]


def test_reconciliation_reports_outbound_orders_without_stock_exit_as_a_warning(week_of_activity):
    # La fixture no tiene filas en stock_exit: los 6 despachos de telemetría no cuadran.
    summary = run_flow()
    reconciliation = [w for w in summary["warnings"] if w["step"] == "check_outbound_reconciliation"]
    assert reconciliation
    differences = {(m["warehouse"], m["client_id"]): m["difference"] for m in reconciliation[0]["mismatches"]}
    assert differences == {("los_angeles", "glowlab_cosmetics"): 2, ("los_angeles", "purestep_footwear"): 4}
    # Un aviso nunca cambia las cifras del reporte.
    assert target_rows(week_of_activity)[1]["outbound_orders_count"] == 4
