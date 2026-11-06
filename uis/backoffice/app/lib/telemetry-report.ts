// Salud del sistema (/telemetry): GET /telemetry/report (hito 17) y ayudas puras para pintarlo.
// La API calcula todas las métricas; aquí solo se suman filas para los gráficos de resumen.

import { ApiError, backofficeFetch } from "./auth";

export type EventsPerDayRow = { date: string; source: string; events: number };
export type EventsByTypeRow = { date: string; event_type: string; events: number; share: number };
export type ErrorRateRow = {
  date: string;
  event_type: string;
  errors: number;
  occurrences: number;
  total_events: number;
  error_rate: number;
};
export type PageLoadRow = {
  date: string;
  page_route: string;
  samples: number;
  ttfb_p50_ms: number | null;
  ttfb_p95_ms: number | null;
  lcp_p50_ms: number | null;
  lcp_p95_ms: number | null;
};
export type AuthFailureRow = { date: string; attempts: number; failed: number; succeeded: number; failure_rate: number };

export type TelemetryReport = {
  period: { from: string; to: string };
  metrics: {
    events_per_day: EventsPerDayRow[];
    events_by_type: EventsByTypeRow[];
    error_rate_by_type: ErrorRateRow[];
    page_load_latency: PageLoadRow[];
    auth_failure_rate: AuthFailureRow[];
  };
};

/** Fechas del formulario (`YYYY-MM-DD`, días UTC) → parámetros de la API. `to` es inclusivo en
 * pantalla y exclusivo en la API: se pide hasta las 00:00 UTC del día siguiente. */
export function reportQuery(from: string, to: string): string {
  const params = new URLSearchParams();
  if (from) params.set("start_date", `${from}T00:00:00Z`);
  if (to) {
    const end = new Date(`${to}T00:00:00Z`);
    end.setUTCDate(end.getUTCDate() + 1);
    params.set("end_date", end.toISOString().replace(".000Z", "Z"));
  }
  const query = params.toString();
  return query ? `?${query}` : "";
}

export async function getTelemetryReport(from = "", to = ""): Promise<TelemetryReport> {
  const response = await backofficeFetch(`/telemetry/report${reportQuery(from, to)}`);
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const detail = typeof body?.detail === "string" ? body.detail : "No se pudo cargar el reporte de telemetría.";
    throw new ApiError(response.status, detail);
  }
  return response.json();
}

/** Suma `value` por `key`, respetando el orden de primera aparición. */
export function sumBy<T>(rows: T[], key: (row: T) => string, value: (row: T) => number): { label: string; value: number }[] {
  const totals = new Map<string, number>();
  for (const row of rows) totals.set(key(row), (totals.get(key(row)) ?? 0) + value(row));
  return [...totals].map(([label, total]) => ({ label, value: total }));
}

/** Eventos totales por día (suma de los orígenes). */
export function eventsByDay(rows: EventsPerDayRow[]) {
  return sumBy(rows, (row) => row.date, (row) => row.events);
}

/** Eventos de cada tipo en todo el periodo, de más a menos. */
export function eventsByTypeInPeriod(rows: EventsByTypeRow[]) {
  return sumBy(rows, (row) => row.event_type, (row) => row.events).sort((a, b) => b.value - a.value);
}

export function formatPercent(rate: number): string {
  return `${(rate * 100).toFixed(rate > 0 && rate < 0.01 ? 2 : 1)} %`;
}

export function formatMs(value: number | null): string {
  return value === null ? "—" : `${Math.round(value).toLocaleString("es-ES")} ms`;
}

/** `2026-11-01T00:00:00Z` → `01/11/2026 00:00 UTC`. */
export function formatUtc(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(date.getUTCDate())}/${pad(date.getUTCMonth() + 1)}/${date.getUTCFullYear()} ${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())} UTC`;
}
