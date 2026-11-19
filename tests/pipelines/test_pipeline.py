"""Tests unitarios de las tasks de transformación del pipeline semanal (hito 20, Fase 2).

Cada test llama a la función de la task (`task.fn`) de data/pipelines/pipeline.py con eventos en
memoria con la forma de la telemetría de TrackFlow (Event Envelope de event-schemas.json). Sin base
de datos, sin servidor de Prefect y sin APIs externas: si algo intenta abrir una conexión, el
test falla (fixture `no_database`).

    python -m pytest tests/pipelines/test_pipeline.py

KPIs del BRIEFING (§2 «KPIs a medir» y §4):

    Volumen de entrada              inbound_units_count   = suma de quantity de inbound_order_created
    Throughput de salida            outbound_orders_count = conteo de outbound_order_created
    Frecuencia de quiebre de stock  stockout_events_count = conteo de stock_threshold_triggered
    Tasa de discrepancia            discrepancy_rate      = discrepancias / pedidos de salida (0 sin salidas)
"""

import itertools
from datetime import date

import pandas as pd
import pytest

from data.pipelines import pipeline
from data.pipelines.weekly_warehouse_client_performance import config, connections

WEEK = date(2026, 11, 2)            # lunes de la semana ISO 45 de 2026
NEXT_WEEK = date(2026, 11, 9)
_ids = itertools.count(1000)

# Las tasks de transformación, por su función (sin el motor de Prefect).
prepare = pipeline.prepare_inventory_events.fn
inbound_volume = pipeline.compute_inbound_volume.fn
outbound_throughput = pipeline.compute_outbound_throughput.fn
stockout_frequency = pipeline.compute_stockout_frequency.fn
discrepancy_rate = pipeline.compute_discrepancy_rate.fn
assemble = pipeline.assemble_weekly_performance.fn

BUSINESS_KEY = {
    "inbound_order_created": "inbound_order_id",
    "outbound_order_created": "outbound_order_id",
    "stock_threshold_triggered": "trigger_order_id",
    "inventory_discrepancy_detected": "count_id",
}


@pytest.fixture(autouse=True)
def no_database(monkeypatch):
    """Garantiza el aislamiento: ninguna transformación debe tocar Supabase."""
    def forbidden():
        raise AssertionError("una task de transformación intentó abrir una conexión a la base de datos")

    monkeypatch.setattr(connections, "reader_engine", forbidden)
    monkeypatch.setattr(connections, "writer_engine", forbidden)


# =========================================================
# Datos de prueba con la forma de la telemetría
# =========================================================


def telemetry_event(event_type, timestamp, *, warehouse="los_angeles", client_id="purestep_footwear",
                    quantity=1, business_id=None):
    """Un evento como lo emite el backoffice (Event Envelope + `properties` del catálogo)."""
    business_id = next(_ids) if business_id is None else business_id
    return {
        "eventId": f"evt-{next(_ids)}",
        "timestamp": timestamp,
        "sessionId": "sess-1",
        "userId": "user-1",
        "event_type": event_type,
        "schemaVersion": "1.0",
        "requestId": "req-1",
        "source": "backoffice",
        "environment": "test",
        "properties": {
            "warehouse": warehouse,
            "client_id": client_id,
            "product_id": "CLT-SNK-W-42",
            "quantity": quantity,
            BUSINESS_KEY[event_type]: business_id,
        },
    }


def as_extracted(events: list[dict]) -> pd.DataFrame:
    """Lo que entrega `extract_inventory_events`: una fila por evento, con sus campos de `tags`."""
    return pd.DataFrame([
        {
            "event_id": event["eventId"],
            "event_type": event["event_type"],
            "timestamp": event["timestamp"],
            "created_at": event["timestamp"],
            "warehouse": event["properties"].get("warehouse"),
            "client_id": event["properties"].get("client_id"),
            "quantity": event["properties"].get("quantity"),
            "business_key": str(event["properties"][BUSINESS_KEY[event["event_type"]]]),
        }
        for event in events
    ])


def known_week() -> list[dict]:
    """Una semana calculable a mano.

    los_angeles × purestep_footwear: entradas de 120 + 300 + 0 unidades, 4 despachos,
    1 quiebre de stock y 1 discrepancia → 420 / 4 / 1 / tasa 1 / 4 = 0.25.
    los_angeles × glowlab_cosmetics: 1 entrada de 80 unidades y 2 despachos → 80 / 2 / 0 / 0.
    zaragoza × purestep_footwear: 1 entrada de 50 unidades y 1 discrepancia sin despachos → tasa 0.
    """
    la, glow, zgz = {}, {"client_id": "glowlab_cosmetics"}, {"warehouse": "zaragoza"}
    return [
        telemetry_event("inbound_order_created", "2026-11-02T08:00:00.000Z", quantity=120, **la),
        telemetry_event("inbound_order_created", "2026-11-03T08:00:00.000Z", quantity=300, **la),
        telemetry_event("inbound_order_created", "2026-11-04T08:00:00.000Z", quantity=0, **la),
        *[telemetry_event("outbound_order_created", f"2026-11-0{day}T10:00:00.000Z", **la) for day in (3, 4, 5, 6)],
        telemetry_event("stock_threshold_triggered", "2026-11-06T10:00:01.000Z", **la),
        telemetry_event("inventory_discrepancy_detected", "2026-11-07T18:00:00.000Z", quantity=2, **la),
        telemetry_event("inbound_order_created", "2026-11-03T09:00:00.000Z", quantity=80, **glow),
        *[telemetry_event("outbound_order_created", f"2026-11-0{day}T11:00:00.000Z", **glow) for day in (4, 5)],
        telemetry_event("inbound_order_created", "2026-11-02T07:00:00.000Z", quantity=50, **zgz),
        telemetry_event("inventory_discrepancy_detected", "2026-11-08T20:00:00.000Z", quantity=1, **zgz),
    ]


@pytest.fixture
def prepared() -> pd.DataFrame:
    return prepare(as_extracted(known_week()), [WEEK]).events


def value(frame: pd.DataFrame, column: str, warehouse="los_angeles", client_id="purestep_footwear"):
    match = frame[(frame["warehouse"] == warehouse) & (frame["client_id"] == client_id)]
    assert len(match) == 1, f"se esperaba una fila para {warehouse} × {client_id}"
    return match.iloc[0][column]


# =========================================================
# Un test por KPI: valor calculado a mano según el BRIEFING
# =========================================================


def test_compute_inbound_volume_sums_the_units_received_not_the_orders(prepared):
    volume = inbound_volume(prepared)
    # Volumen de entrada = 120 + 300 + 0 = 420 unidades (3 órdenes, pero se suman unidades).
    assert value(volume, "inbound_units_count") == 420
    assert value(volume, "inbound_units_count", client_id="glowlab_cosmetics") == 80
    assert value(volume, "inbound_units_count", warehouse="zaragoza") == 50


def test_compute_outbound_throughput_counts_dispatched_orders(prepared):
    throughput = outbound_throughput(prepared)
    assert value(throughput, "outbound_orders_count") == 4
    assert value(throughput, "outbound_orders_count", client_id="glowlab_cosmetics") == 2
    assert throughput[throughput["warehouse"] == "zaragoza"].empty      # sin despachos, sin fila


def test_compute_stockout_frequency_counts_each_crossing_of_the_minimum(prepared):
    stockouts = stockout_frequency(prepared)
    assert value(stockouts, "stockout_events_count") == 1
    assert len(stockouts) == 1


def test_compute_discrepancy_rate_matches_the_briefing_definition(prepared):
    rates = discrepancy_rate(prepared, outbound_throughput(prepared))
    # Tasa de discrepancia = discrepancias / pedidos de salida = 1 / 4 = 0.25.
    assert value(rates, "discrepancy_events_count") == 1
    assert value(rates, "discrepancy_rate") == pytest.approx(1 / 4)
    assert value(rates, "discrepancy_rate", client_id="glowlab_cosmetics") == 0.0     # 0 / 2


def test_discrepancy_rate_is_zero_when_there_were_no_outbound_orders(prepared):
    rates = discrepancy_rate(prepared, outbound_throughput(prepared))
    # Zaragoza: 1 discrepancia y 0 pedidos de salida → 0 (BRIEFING §4), no una división por cero.
    assert value(rates, "discrepancy_events_count", warehouse="zaragoza") == 1
    assert value(rates, "discrepancy_rate", warehouse="zaragoza") == 0.0


def test_discrepancy_rate_is_rounded_to_four_decimals():
    events = [telemetry_event("outbound_order_created", f"2026-11-0{day}T10:00:00.000Z") for day in (2, 3, 4)]
    events.append(telemetry_event("inventory_discrepancy_detected", "2026-11-05T10:00:00.000Z"))
    week = prepare(as_extracted(events), [WEEK]).events
    assert value(discrepancy_rate(week, outbound_throughput(week)), "discrepancy_rate") == 0.3333   # 1 / 3


def test_assemble_weekly_performance_builds_the_briefing_table_for_a_known_week(prepared):
    outbound = outbound_throughput(prepared)
    weekly = assemble(inbound_volume(prepared), outbound, stockout_frequency(prepared), discrepancy_rate(prepared, outbound))

    assert list(weekly.columns) == ["warehouse", "client_id", "week_start", *config.KPI_COLUMNS]
    rows = weekly.set_index(["warehouse", "client_id"]).to_dict(orient="index")
    assert rows == {
        ("los_angeles", "glowlab_cosmetics"): {"week_start": WEEK, "inbound_units_count": 80, "outbound_orders_count": 2,
                                               "stockout_events_count": 0, "discrepancy_events_count": 0, "discrepancy_rate": 0.0},
        ("los_angeles", "purestep_footwear"): {"week_start": WEEK, "inbound_units_count": 420, "outbound_orders_count": 4,
                                               "stockout_events_count": 1, "discrepancy_events_count": 1, "discrepancy_rate": 0.25},
        ("zaragoza", "purestep_footwear"): {"week_start": WEEK, "inbound_units_count": 50, "outbound_orders_count": 0,
                                            "stockout_events_count": 0, "discrepancy_events_count": 1, "discrepancy_rate": 0.0},
    }


def test_a_row_never_mixes_clients(prepared):
    outbound = outbound_throughput(prepared)
    weekly = assemble(inbound_volume(prepared), outbound, stockout_frequency(prepared), discrepancy_rate(prepared, outbound))
    assert not weekly.duplicated(subset=["warehouse", "client_id", "week_start"]).any()
    assert set(weekly["client_id"]) == {"purestep_footwear", "glowlab_cosmetics"}


# =========================================================
# prepare_inventory_events: semanas ISO, deduplicación
# =========================================================


def test_prepare_assigns_each_event_to_its_iso_week_in_utc():
    events = as_extracted([
        telemetry_event("outbound_order_created", "2026-11-08T23:59:59.999Z"),   # domingo → semana del 2
        telemetry_event("outbound_order_created", "2026-11-09T00:00:00.000Z"),   # lunes → semana del 9
    ])
    result = prepare(events, [WEEK, NEXT_WEEK])
    assert sorted(result.events["week_start"]) == [WEEK, NEXT_WEEK]
    assert len(prepare(events, [WEEK]).events) == 1                          # solo las semanas pedidas


def test_prepare_counts_a_movement_sent_twice_only_once():
    dispatch = telemetry_event("outbound_order_created", "2026-11-03T10:00:00.000Z", business_id=7)
    resent = {**dispatch, "eventId": "evt-reenviado", "timestamp": "2026-11-03T10:00:02.000Z"}
    result = prepare(as_extracted([dispatch, resent]), [WEEK])
    assert result.events_deduplicated == 1
    assert value(outbound_throughput(result.events), "outbound_orders_count") == 1


# =========================================================
# Comportamiento defensivo ante entradas inválidas
# =========================================================


def test_prepare_discards_malformed_events_instead_of_failing():
    good = telemetry_event("inbound_order_created", "2026-11-03T08:00:00.000Z", quantity=10)
    malformed = [
        telemetry_event("inbound_order_created", "2026-11-03T08:00:00.000Z", client_id=None),        # nulo
        telemetry_event("inbound_order_created", "2026-11-03T08:00:00.000Z", client_id="   "),       # vacío
        telemetry_event("inbound_order_created", "2026-11-03T08:00:00.000Z", quantity="doce"),       # tipo incorrecto
        telemetry_event("inbound_order_created", "2026-11-03T08:00:00.000Z", quantity=None),         # nulo
        telemetry_event("inbound_order_created", "2026-11-03T08:00:00.000Z", quantity=-5),           # negativo
        telemetry_event("inbound_order_created", "2026-11-03T08:00:00.000Z", warehouse="madrid"),    # almacén desconocido
        telemetry_event("inbound_order_created", "ayer por la tarde", quantity=10),                  # fecha ilegible
        telemetry_event("inbound_order_created", None, quantity=10),                                 # sin fecha
    ]
    result = prepare(as_extracted([good, *malformed]), [WEEK])

    assert (result.events_in, result.events_discarded) == (9, 8)
    assert value(inbound_volume(result.events), "inbound_units_count") == 10    # solo cuenta el válido


def test_a_kpi_task_rejects_an_input_without_the_columns_it_needs(prepared):
    with pytest.raises(ValueError, match=r"inbound_volume: faltan las columnas \['quantity'\]"):
        inbound_volume(prepared.drop(columns="quantity"))
    with pytest.raises(ValueError, match="week_start"):
        outbound_throughput(prepared.drop(columns="week_start"))
    with pytest.raises(TypeError, match="se esperaba un DataFrame"):
        stockout_frequency([{"event_type": "stock_threshold_triggered"}])
    with pytest.raises(ValueError, match="outbound_orders_count"):
        discrepancy_rate(prepared, pd.DataFrame(columns=["warehouse", "client_id", "week_start"]))


def test_a_week_without_events_yields_an_empty_table_not_an_error():
    empty = prepare(as_extracted([]).reindex(columns=["event_id", "event_type", "timestamp", "created_at", "warehouse",
                                                      "client_id", "quantity", "business_key"]), [WEEK])
    outbound = outbound_throughput(empty.events)
    weekly = assemble(inbound_volume(empty.events), outbound, stockout_frequency(empty.events),
                      discrepancy_rate(empty.events, outbound))
    assert weekly.empty
    assert list(weekly.columns) == ["warehouse", "client_id", "week_start", *config.KPI_COLUMNS]
