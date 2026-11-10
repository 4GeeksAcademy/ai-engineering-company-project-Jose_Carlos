"""Subflows del pipeline (hito 20, Fase 1): uno por etapa, con entradas y salidas explícitas,
ejecutables por separado. El flow principal solo los orquesta."""

import ast
import inspect
import textwrap

import pytest
from prefect import Flow

from data.pipelines import pipeline
from data.pipelines.weekly_warehouse_client_performance.load import LoadResult
from data.pipelines.weekly_warehouse_client_performance.transform import WeeklyPerformance
from tests.reporting.conftest import AS_OF, ENVIRONMENT, WEEK

pytestmark = pytest.mark.usefixtures("prefect_server")

CRITICAL_SUBFLOWS = (
    pipeline.extract_inventory_activity,
    pipeline.compute_weekly_warehouse_client_kpis,
    pipeline.load_weekly_warehouse_client_performance,
)
OPTIONAL_SUBFLOWS = (pipeline.reconcile_outbound_throughput, pipeline.export_weekly_performance_snapshot)


def test_every_stage_is_a_prefect_subflow_named_after_the_business_metric():
    assert all(isinstance(subflow, Flow) for subflow in (*CRITICAL_SUBFLOWS, *OPTIONAL_SUBFLOWS))
    assert [subflow.name for subflow in CRITICAL_SUBFLOWS] == [
        "extract-inventory-activity", "compute-weekly-warehouse-client-kpis", "load-weekly-warehouse-client-performance",
    ]


def _main_flow_calls() -> list[tuple[str, bool]]:
    """(nombre, ¿con return_state=True?) de cada llamada dentro del flow principal."""
    source = textwrap.dedent(inspect.getsource(pipeline.weekly_warehouse_client_performance_flow.fn))
    calls = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            with_state = any(k.arg == "return_state" and getattr(k.value, "value", None) is True for k in node.keywords)
            calls.append((node.func.id, with_state))
    return calls


def test_the_main_flow_invokes_the_subflows_and_holds_no_etl_logic():
    calls = dict(_main_flow_calls())
    for subflow in (*CRITICAL_SUBFLOWS, *OPTIONAL_SUBFLOWS):
        assert calls.get(subflow.fn.__name__) is True, subflow.fn.__name__   # invocado con return_state=True
    source = inspect.getsource(pipeline.weekly_warehouse_client_performance_flow.fn)
    assert not any(f"{module}." in source for module in ("extract", "transform", "load", "quality"))


def test_each_subflow_runs_on_its_own_with_explicit_inputs_and_outputs(week_of_activity, tmp_path):
    activity = pipeline.extract_inventory_activity(AS_OF, AS_OF, ENVIRONMENT, week_start=WEEK, lookback_weeks=0,
                                                   include_late_arrivals=False)
    assert isinstance(activity, pipeline.InventoryActivity)
    assert activity.weeks == [WEEK] and len(activity.events) == 13

    kpis = pipeline.compute_weekly_warehouse_client_kpis(activity.events, activity.weeks)
    assert isinstance(kpis, WeeklyPerformance)
    assert len(kpis.weekly) == 3 and kpis.events_in == 13

    loaded = pipeline.load_weekly_warehouse_client_performance(kpis.weekly, activity.weeks, AS_OF)
    assert loaded == LoadResult(rows_upserted=3, rows_deleted=0)

    mismatches = pipeline.reconcile_outbound_throughput(kpis.weekly, activity.weeks)
    assert {(m["client_id"], m["difference"]) for m in mismatches} == {("glowlab_cosmetics", 2), ("purestep_footwear", 4)}

    paths = pipeline.export_weekly_performance_snapshot(kpis.weekly, activity.weeks, AS_OF)
    assert [path.rsplit("week_start=", 1)[1] for path in paths] == [f"{WEEK.isoformat()}.json"]


def test_a_failing_kpi_task_fails_its_subflow_and_the_run_stops_at_transform(week_of_activity, monkeypatch):
    from data.pipelines.weekly_warehouse_client_performance import transform

    def broken(events):
        raise ValueError("inbound_volume: faltan las columnas ['quantity']")

    monkeypatch.setattr(transform, "TRANSFORM_VERSION", "test-broken")   # sin caché de otras corridas
    monkeypatch.setattr(transform, "inbound_volume", broken)
    with pytest.raises(pipeline.PipelineStageError) as error:
        pipeline.weekly_warehouse_client_performance_flow(as_of=AS_OF, lookback_weeks=0)
    assert error.value.stage == "transform"
    assert "faltan las columnas" in error.value.message
