"""Pipeline de análisis de la telemetría (hito 17): métricas operacionales con Pandas.

Responde a "¿qué tan sano está el sistema?" a partir de `telemetry_events`: volumen, qué
tipos de evento dominan, tasa de errores, latencia de carga y fallos de login. Nada de
negocio (conversión, ingresos, pedidos por cliente): eso es el hito de Data Pipelines.

Cada métrica es una función independiente y sin efectos secundarios con la misma firma,
`métrica(start, end, session=None) -> list[dict]`, y sigue siempre los mismos pasos:

    1. Cargar (SQL)          solo las columnas y filas que necesita: ventana
                             `start <= timestamp < end` y, si aplica, `event_type IN (...)`.
    2. Refinar (Pandas)      extraer campos de `tags`, descartar dimensiones nulas, flags.
    3. Convertir tipos       `pd.to_datetime(..., utc=True)` ANTES de agrupar: agrupar
                             strings que parecen fechas da grupos incorrectos sin ningún error.
    4. Agrupar               `groupby()` por la dimensión que responde la pregunta (día, tipo,
                             ruta…). Ninguna métrica es un número global sin contexto.
    5. Agregar               `.agg()` / `.count()` / `.sum()` / `.mean()`; nunca bucles.

y devuelve `reset_index().to_dict(orient="records")`: una lista de dicts serializable a JSON
(fechas como `YYYY-MM-DD`, NaN como `null`).

- La ventana la decide quien llama (el endpoint GET /telemetry/report, que pone los últimos 7
  días por defecto) y llega ya resuelta: aquí no hay `now()` ni "últimos 7 días" en Pandas.
  Por eso la misma llamada con los mismos parámetros da siempre el mismo resultado.
- Todos los días son días UTC (los timestamps se guardan en UTC).
- `session` permite reutilizar una sesión (lo hace `build_report`); sin ella, cada función
  abre la suya con `services.telemetry.open_session` (los tests la sustituyen por un SQLite).
"""

from contextlib import nullcontext
from datetime import datetime, timedelta
from typing import Any, Callable

import pandas as pd
from sqlalchemy import select
from sqlmodel import Session

from services import telemetry
from services.telemetry_models import TelemetryEventRecord


TABLE = TelemetryEventRecord.__table__

# Errores del SISTEMA (algo se rompió), no rechazos de negocio: un `outbound_order_rejected`
# por falta de stock o un `order_validation_failed` son la API funcionando bien.
# `login_failed` tiene su propia métrica (auth_failure_rate).
ERROR_EVENT_TYPES = (
    "api_error_occurred",          # excepción no controlada en la API
    "api_request_failed",          # el navegador no obtuvo respuesta válida (red, timeout, 5xx)
    "database_connection_failed",  # la API no pudo hablar con Supabase
    "frontend_error_captured",     # error JS no controlado en el backoffice
    "password_reset_email_failed", # el proveedor de correo falló
)

PAGE_LOAD_EVENT = "page_load_recorded"
LOGIN_FAILED_EVENT = "login_failed"
LOGIN_SUCCEEDED_EVENT = "user_logged_in"
# `login_failed` solo lo emite el formulario del backoffice, que llama a /auth/login
# (`auth_method = password_json`). Los logins por Swagger (/auth/token) no tienen fallo
# equivalente medido: contarlos inflaría el denominador.
BACKOFFICE_AUTH_METHOD = "password_json"

# Las ventanas más largas que esto cargarían demasiadas filas en memoria de una vez.
MAX_WINDOW = timedelta(days=90)


# =========================================================
# PASOS COMUNES
# =========================================================


def check_window(start: datetime, end: datetime) -> None:
    """La ventana `[start, end)` debe ser UTC explícita, no vacía y de como mucho 90 días."""
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("start y end deben llevar zona horaria (UTC)")
    if start >= end:
        raise ValueError("start debe ser anterior a end")
    if end - start > MAX_WINDOW:
        raise ValueError(f"la ventana no puede superar {MAX_WINDOW.days} días")


def _load(
    session: Session | None,
    start: datetime,
    end: datetime,
    columns: list,
    event_types: tuple[str, ...] | None = None,
) -> pd.DataFrame:
    """Paso 1 — Cargar (SQL): las columnas pedidas de las filas de la ventana y los tipos dados.

    `WHERE timestamp >= :start AND timestamp < :end [AND event_type IN (...)]`: inicio
    inclusivo y fin exclusivo, así dos ventanas contiguas nunca cuentan el mismo evento.
    Usa los índices `ix_telemetry_events_timestamp` e `ix_telemetry_events_event_type`.
    """
    check_window(start, end)
    statement = select(*columns).where(TABLE.c.timestamp >= start, TABLE.c.timestamp < end)
    if event_types is not None:
        statement = statement.where(TABLE.c.event_type.in_(event_types))
    with nullcontext(session) if session is not None else telemetry.open_session() as active:
        rows = active.execute(statement).mappings().all()
    return pd.DataFrame(rows, columns=[column.name for column in columns])


def _extract_tags(df: pd.DataFrame, *fields: str) -> pd.DataFrame:
    """Paso 2 — Refinar: saca campos de `tags` a columnas (NaN si el evento no los lleva)."""
    tags = pd.json_normalize(df["tags"].tolist()).reindex(columns=list(fields))
    tags.index = df.index
    return pd.concat([df.drop(columns="tags"), tags], axis=1)


def _with_dates(df: pd.DataFrame) -> pd.DataFrame:
    """Paso 3 — Convertir tipos: `timestamp` a datetime UTC y su día UTC en `date`.

    Llega como datetime (PostgreSQL) o como texto (SQLite). Sin esta conversión,
    `groupby("timestamp")` agruparía strings y, p. ej., "2026-11-04T23:59:59+01:00" y
    "2026-11-04T22:59:59Z" (el mismo instante) caerían en grupos distintos sin avisar.
    """
    df = df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, format="ISO8601")
    df["date"] = df["timestamp"].dt.date
    return df


def _records(result: pd.DataFrame) -> list[dict[str, Any]]:
    """Paso final: lista de dicts lista para JSON (fechas ISO, NaN → None, tipos nativos)."""
    result = result.reset_index()
    if "date" in result.columns:
        result["date"] = result["date"].map(lambda day: day.isoformat())
    result = result.astype(object).where(result.notna(), None)
    return result.to_dict(orient="records")


# =========================================================
# MÉTRICAS
# =========================================================


def events_per_day(start: datetime, end: datetime, session: Session | None = None) -> list[dict[str, Any]]:
    """Volumen: eventos guardados por día y origen (`api` | `backoffice_web`).

    Pregunta: ¿llega telemetría de las dos partes del sistema? Un día con `api` pero sin
    `backoffice_web` (o al revés) es un emisor caído o un TelemetryService que no envía.
    Filas: `{date, source, events}`.
    """
    df = _load(session, start, end, [TABLE.c.timestamp, TABLE.c.source])
    if df.empty:
        return []
    df = _with_dates(df)
    result = df.groupby(["date", "source"]).agg(events=("timestamp", "count"))
    return _records(result)


def events_by_type(start: datetime, end: datetime, session: Session | None = None) -> list[dict[str, Any]]:
    """Composición: qué tipos de evento dominan cada día y qué parte del volumen son.

    Pregunta: ¿cambió de golpe la mezcla? Un tipo que pasa de 2 % a 60 % del día es un bucle
    de emisión o un fallo en cascada, aunque el volumen total parezca normal.
    Filas: `{date, event_type, events, share}`, de mayor a menor dentro de cada día.
    """
    df = _load(session, start, end, [TABLE.c.timestamp, TABLE.c.event_type])
    if df.empty:
        return []
    df = _with_dates(df)
    result = df.groupby(["date", "event_type"]).agg(events=("timestamp", "count"))
    result["share"] = (result["events"] / result.groupby(level="date")["events"].transform("sum")).round(4)
    result = result.sort_values(["date", "events"], ascending=[True, False])
    return _records(result)


def error_rate_by_type(start: datetime, end: datetime, session: Session | None = None) -> list[dict[str, Any]]:
    """Errores: tasa diaria de cada tipo de error del sistema sobre el total de eventos del día.

    Pregunta: ¿qué se está rompiendo y cuánto pesa en la actividad del día?
    - `errors`: eventos de error de ese tipo. `error_rate = errors / total_events` del día.
    - `occurrences`: errores reales. El navegador deduplica (`frontend_error_captured` agrupa
      repeticiones en `occurrences`) y la API agrega por ventana (`database_connection_failed`);
      los demás valen 1 por evento.
    Una tasa necesita numerador y denominador de la misma consulta: se cargan todos los tipos
    de la ventana (sin `tags`; de ahí solo se trae `occurrences`, extraído en SQL).
    Filas: `{date, event_type, errors, occurrences, total_events, error_rate}`.
    """
    occurrences = TABLE.c.tags["occurrences"].as_integer().label("occurrences")
    df = _load(session, start, end, [TABLE.c.timestamp, TABLE.c.event_type, occurrences])
    if df.empty:
        return []
    df["is_error"] = df["event_type"].isin(ERROR_EVENT_TYPES)
    df["occurrences"] = df["occurrences"].fillna(1)
    df = _with_dates(df)
    totals = df.groupby("date").agg(total_events=("event_type", "count"))
    errors = (
        df[df["is_error"]]
        .groupby(["date", "event_type"])
        .agg(errors=("event_type", "count"), occurrences=("occurrences", "sum"))
    )
    if errors.empty:
        return []
    result = errors.join(totals, on="date")
    result["occurrences"] = result["occurrences"].astype(int)
    result["error_rate"] = (result["errors"] / result["total_events"]).round(4)
    return _records(result)


def _p95(values: pd.Series) -> float:
    return values.quantile(0.95)


def page_load_latency(start: datetime, end: datetime, session: Session | None = None) -> list[dict[str, Any]]:
    """Latencia: tiempos de carga reales del backoffice por día y ruta (`page_load_recorded`).

    Pregunta: ¿qué pantallas van lentas y desde cuándo? `ttfb_ms` es lo que tarda en llegar el
    primer byte (servidor + red); `lcp_ms`, cuándo se ve el contenido principal (umbral "bueno"
    de Core Web Vitals: 2500 ms). Percentiles y no medias: un puñado de cargas muy lentas
    hunde la experiencia sin mover la media. Las rutas nulas se descartan.
    Filas: `{date, page_route, samples, ttfb_p50_ms, ttfb_p95_ms, lcp_p50_ms, lcp_p95_ms}`.
    """
    df = _load(session, start, end, [TABLE.c.timestamp, TABLE.c.tags], event_types=(PAGE_LOAD_EVENT,))
    if df.empty:
        return []
    df = _extract_tags(df, "page_route", "ttfb_ms", "lcp_ms").dropna(subset=["page_route"])
    df[["ttfb_ms", "lcp_ms"]] = df[["ttfb_ms", "lcp_ms"]].apply(pd.to_numeric, errors="coerce")
    df = _with_dates(df)
    result = df.groupby(["date", "page_route"]).agg(
        samples=("timestamp", "count"),
        ttfb_p50_ms=("ttfb_ms", "median"),
        ttfb_p95_ms=("ttfb_ms", _p95),
        lcp_p50_ms=("lcp_ms", "median"),
        lcp_p95_ms=("lcp_ms", _p95),
    )
    latency_columns = ["ttfb_p50_ms", "ttfb_p95_ms", "lcp_p50_ms", "lcp_p95_ms"]
    result[latency_columns] = result[latency_columns].round(0)
    return _records(result)


def auth_failure_rate(start: datetime, end: datetime, session: Session | None = None) -> list[dict[str, Any]]:
    """Autenticación: tasa diaria de fallos de login del backoffice.

    `failure_rate = login_failed / (login_failed + user_logged_in)` por día. Ambos tipos se
    cargan en UNA consulta (`event_type IN (...)`) y la razón se calcula en Pandas. Solo
    cuentan los éxitos de `/auth/login` (`auth_method = password_json`), el mismo formulario
    que emite `login_failed`. Un pico es un problema de acceso (API caída, formulario roto) o
    un intento de fuerza bruta.
    Filas: `{date, attempts, failed, succeeded, failure_rate}`.
    """
    df = _load(
        session, start, end, [TABLE.c.timestamp, TABLE.c.event_type, TABLE.c.tags],
        event_types=(LOGIN_FAILED_EVENT, LOGIN_SUCCEEDED_EVENT),
    )
    if df.empty:
        return []
    df = _extract_tags(df, "auth_method")
    df = df[(df["event_type"] == LOGIN_FAILED_EVENT) | (df["auth_method"] == BACKOFFICE_AUTH_METHOD)].copy()
    df["failed"] = df["event_type"] == LOGIN_FAILED_EVENT
    df["succeeded"] = ~df["failed"]
    if df.empty:
        return []
    df = _with_dates(df)
    result = df.groupby("date").agg(
        attempts=("event_type", "count"), failed=("failed", "sum"), succeeded=("succeeded", "sum")
    )
    result["failure_rate"] = (result["failed"] / result["attempts"]).round(4)
    return _records(result)


# =========================================================
# REPORTE
# =========================================================

Metric = Callable[[datetime, datetime, Session | None], list[dict[str, Any]]]

# Las claves de `metrics` en GET /telemetry/report, en este orden.
METRICS: dict[str, Metric] = {
    "events_per_day": events_per_day,
    "events_by_type": events_by_type,
    "error_rate_by_type": error_rate_by_type,
    "page_load_latency": page_load_latency,
    "auth_failure_rate": auth_failure_rate,
}


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds").replace("+00:00", "Z")


def build_report(start: datetime, end: datetime, session: Session | None = None) -> dict[str, Any]:
    """Todas las métricas para la ventana `[start, end)`, con una sola sesión de base de datos.

    `{"period": {"from", "to"}, "metrics": {nombre: [filas]}}`. No cachea: eso es del
    endpoint, que decide cuándo volver a llamar.
    """
    check_window(start, end)
    with nullcontext(session) if session is not None else telemetry.open_session() as active:
        metrics = {name: metric(start, end, active) for name, metric in METRICS.items()}
    return {"period": {"from": _iso(start), "to": _iso(end)}, "metrics": metrics}
