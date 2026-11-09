"""Resiliencia del flow (hito 19, Fase 2): reintentos, fallos explícitos y caché."""

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from data.pipelines import pipeline
from data.pipelines.weekly_warehouse_client_performance import extract, load, transform
from data.pipelines.weekly_warehouse_client_performance.schema import weekly_warehouse_client_performance as TARGET
from tests.reporting.conftest import AS_OF, inventory_event, store

pytestmark = pytest.mark.usefixtures("prefect_server")


def connection_lost() -> OperationalError:
    return OperationalError("SELECT ...", {}, Exception("server closed the connection unexpectedly"))


def run_flow(**parameters):
    parameters.setdefault("as_of", AS_OF)
    parameters.setdefault("lookback_weeks", 0)
    return pipeline.weekly_warehouse_client_performance_flow(**parameters)


def count_rows(engine) -> int:
    with engine.connect() as connection:
        return connection.execute(select(func.count()).select_from(TARGET)).scalar_one()


@pytest.fixture
def no_retry_delay(monkeypatch):
    """Mismos reintentos que en producción, sin esperar entre ellos."""
    for name in ("resolve_weeks_to_process", "extract_inventory_events", "load_weekly_performance"):
        monkeypatch.setattr(pipeline, name, getattr(pipeline, name).with_options(retry_delay_seconds=0))


@pytest.fixture
def calls(monkeypatch):
    """Envuelve una función pura para contar sus llamadas y, opcionalmente, hacerla fallar."""
    counter = {}

    def wrap(module, name, failures=()):
        original = getattr(module, name)
        counter[name] = 0
        pending = list(failures)

        def wrapper(*args, **kwargs):
            counter[name] += 1
            if pending:
                raise pending.pop(0)
            return original(*args, **kwargs)

        monkeypatch.setattr(module, name, wrapper)

    wrap.counter = counter
    return wrap


def test_database_tasks_declare_retries_and_the_transform_does_not():
    assert pipeline.extract_inventory_events.retries == 3
    assert pipeline.resolve_weeks_to_process.retries == 3
    assert pipeline.load_weekly_performance.retries == 2
    assert pipeline.check_outbound_reconciliation.retries == 1
    assert pipeline.transform_weekly_performance.retries == 0


def test_a_transient_extraction_error_is_retried_and_the_run_completes(week_of_activity, no_retry_delay, calls):
    calls(extract, "extract_inventory_events", failures=[connection_lost()])
    summary = run_flow()
    assert calls.counter["extract_inventory_events"] == 2
    assert summary["rows_upserted"] == 3


def test_a_non_transient_error_is_not_retried(week_of_activity, no_retry_delay, calls):
    calls(extract, "extract_inventory_events", failures=[KeyError("tags")] * 4)
    with pytest.raises(pipeline.PipelineStageError) as error:
        run_flow()
    assert error.value.stage == "extract"
    assert calls.counter["extract_inventory_events"] == 1


def test_a_load_that_keeps_failing_stops_the_run_with_its_stage(week_of_activity, no_retry_delay, calls):
    calls(load, "load_weekly_performance", failures=[connection_lost()] * 3)
    with pytest.raises(pipeline.PipelineStageError) as error:
        run_flow()
    assert error.value.stage == "load"
    assert calls.counter["load_weekly_performance"] == 3     # 1 intento + 2 reintentos
    assert count_rows(week_of_activity) == 0


def test_the_transform_is_reused_from_cache_while_the_input_is_the_same(week_of_activity, calls):
    calls(transform, "transform_weekly_performance")
    first = run_flow()
    second = run_flow()
    assert calls.counter["transform_weekly_performance"] == 1     # la segunda corrida usa la caché
    assert first["rows_upserted"] == second["rows_upserted"] == 3

    # Un evento nuevo cambia la entrada → otra clave de caché → se recalcula.
    store(week_of_activity, inventory_event("outbound_order_created", "2026-11-06T09:00:00.000Z"))
    run_flow()
    assert calls.counter["transform_weekly_performance"] == 2


def test_the_cache_key_depends_on_events_weeks_and_version(week_of_activity):
    weeks = [AS_OF.date()]
    events = extract.extract_inventory_events(week_of_activity, [extract.config.last_closed_week(AS_OF)], AS_OF, "test")
    key = pipeline.transform_cache_key(None, {"events": events, "weeks": weeks})
    assert key == pipeline.transform_cache_key(None, {"events": events.copy(), "weeks": list(weeks)})
    assert key != pipeline.transform_cache_key(None, {"events": events.iloc[1:], "weeks": weeks})
    assert key != pipeline.transform_cache_key(None, {"events": events, "weeks": []})
    assert f"-v{transform.TRANSFORM_VERSION}-" in key
    assert pipeline.TRANSFORM_CACHE_EXPIRATION.total_seconds() == 3600
