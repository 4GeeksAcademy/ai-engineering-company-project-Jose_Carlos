// Reporte semanal de desempeño (/reporting): GET /reporting/weekly-warehouse-client-performance
// (hito 19) y ayudas puras para presentarlo a dirección. Los KPIs los calcula el pipeline; aquí solo
// se ponen nombres legibles, se formatea el periodo y se suman totales de la semana.

import { ApiError, backofficeFetch } from "./auth";

export type WeeklyPerformanceEntry = {
  warehouse: "los_angeles" | "zaragoza";
  client_id: string;
  inbound_units_count: number;
  outbound_orders_count: number;
  stockout_events_count: number;
  discrepancy_events_count: number;
  discrepancy_rate: number;
};

export type WeeklyPerformanceReport = {
  week_start: string;
  computed_at: string | null;
  entries: WeeklyPerformanceEntry[];
};

/** Los cuatro KPIs de «KPIs a medir» del BRIEFING, con su nombre exacto y qué miden. */
export const KPIS = [
  {
    key: "inbound_units_count",
    name: "Volumen de entrada",
    unit: "unidades recibidas",
    measures: "Cuántas unidades de mercancía de cada cliente recibió cada almacén durante la semana.",
  },
  {
    key: "outbound_orders_count",
    name: "Throughput de salida",
    unit: "pedidos despachados",
    measures: "Cuántos pedidos preparó y despachó cada almacén para cada cliente durante la semana.",
  },
  {
    key: "stockout_events_count",
    name: "Frecuencia de quiebre de stock",
    unit: "veces por debajo del mínimo",
    measures: "Cuántas veces durante la semana el stock de un cliente en un almacén cayó por debajo del mínimo configurado.",
  },
  {
    key: "discrepancy_rate",
    name: "Tasa de discrepancia",
    unit: "de los pedidos de salida",
    measures: "Qué proporción de los pedidos de salida de la semana se asoció a una discrepancia de inventario detectada.",
  },
] as const;

export type KpiKey = (typeof KPIS)[number]["key"];

export const WAREHOUSE_LABELS: Record<string, string> = { los_angeles: "Los Ángeles", zaragoza: "Zaragoza" };

const MONTHS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"];
const DAY_MS = 24 * 60 * 60 * 1000;

/** Error de «no hay datos de esa semana» (404): no es un fallo, es un estado vacío. */
export class NoReportForWeek extends Error {}

export async function getWeeklyPerformance(weekStart = ""): Promise<WeeklyPerformanceReport> {
  const query = weekStart ? `?week_start=${encodeURIComponent(weekStart)}` : "";
  const response = await backofficeFetch(`/reporting/weekly-warehouse-client-performance${query}`);
  if (response.status === 404) throw new NoReportForWeek(weekStart ? "No hay datos de esta semana." : "Todavía no hay ninguna semana calculada.");
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const detail = typeof body?.detail === "string" ? body.detail : "No se pudo cargar el reporte semanal.";
    throw new ApiError(response.status, detail);
  }
  return response.json();
}

function utcDate(isoDay: string): Date {
  return new Date(`${isoDay}T00:00:00Z`);
}

function isoDay(date: Date): string {
  return date.toISOString().slice(0, 10);
}

/** `2026-11-02` → «Semana del 2 al 8 de noviembre de 2026» (lunes a domingo, UTC). */
export function formatWeek(weekStart: string): string {
  const start = utcDate(weekStart);
  const end = new Date(start.getTime() + 6 * DAY_MS);
  const [d1, m1, y1] = [start.getUTCDate(), start.getUTCMonth(), start.getUTCFullYear()];
  const [d2, m2, y2] = [end.getUTCDate(), end.getUTCMonth(), end.getUTCFullYear()];
  if (y1 !== y2) return `Semana del ${d1} de ${MONTHS[m1]} de ${y1} al ${d2} de ${MONTHS[m2]} de ${y2}`;
  if (m1 !== m2) return `Semana del ${d1} de ${MONTHS[m1]} al ${d2} de ${MONTHS[m2]} de ${y2}`;
  return `Semana del ${d1} al ${d2} de ${MONTHS[m2]} de ${y2}`;
}

/** El lunes `weeks` semanas antes (negativo) o después (positivo). */
export function shiftWeek(weekStart: string, weeks: number): string {
  return isoDay(new Date(utcDate(weekStart).getTime() + weeks * 7 * DAY_MS));
}

/** Lunes de la última semana ya cerrada (la que el pipeline publica cada lunes). */
export function lastClosedWeek(now: Date): string {
  const today = utcDate(isoDay(now));
  const sinceMonday = (today.getUTCDay() + 6) % 7;
  return isoDay(new Date(today.getTime() - (sinceMonday + 7) * DAY_MS));
}

/** `2026-11-09T18:49:34Z` → «9 de noviembre de 2026, 18:49 UTC». */
export function formatUpdatedAt(computedAt: string | null): string {
  if (!computedAt) return "fecha no disponible";
  const moment = new Date(computedAt);
  const time = moment.toISOString().slice(11, 16);
  return `${moment.getUTCDate()} de ${MONTHS[moment.getUTCMonth()]} de ${moment.getUTCFullYear()}, ${time} UTC`;
}

/** `soundwave_electronics` → «Soundwave Electronics». */
export function clientLabel(clientId: string): string {
  return clientId
    .split(/[_-]+/)
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

export function entryLabel(entry: Pick<WeeklyPerformanceEntry, "warehouse" | "client_id">): string {
  return `${WAREHOUSE_LABELS[entry.warehouse] ?? entry.warehouse} · ${clientLabel(entry.client_id)}`;
}

export function formatCount(value: number): string {
  return new Intl.NumberFormat("es-ES").format(value);
}

/** 0.25 → «25 %»; 0.0033 → «0,33 %». */
export function formatRate(rate: number): string {
  const percent = rate * 100;
  const digits = percent === 0 || percent >= 10 || Number.isInteger(percent) ? 0 : percent < 1 ? 2 : 1;
  return `${new Intl.NumberFormat("es-ES", { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(percent)} %`;
}

export function formatKpi(key: KpiKey, value: number): string {
  return key === "discrepancy_rate" ? formatRate(value) : formatCount(value);
}

/** Totales de la semana. La tasa total se recalcula con su definición (discrepancias / pedidos de
 * salida de todas las combinaciones), no como media de tasas. */
export function weekTotals(entries: WeeklyPerformanceEntry[]): Record<KpiKey, number> {
  const sum = (key: keyof WeeklyPerformanceEntry) => entries.reduce((total, entry) => total + Number(entry[key]), 0);
  const outbound = sum("outbound_orders_count");
  const discrepancies = sum("discrepancy_events_count");
  return {
    inbound_units_count: sum("inbound_units_count"),
    outbound_orders_count: outbound,
    stockout_events_count: sum("stockout_events_count"),
    discrepancy_rate: outbound > 0 ? Math.round((discrepancies / outbound) * 10000) / 10000 : 0,
  };
}

/** Filas de un KPI, de mayor a menor, con la etiqueta «Almacén · Cliente». */
export function kpiBars(entries: WeeklyPerformanceEntry[], key: KpiKey): { label: string; value: number }[] {
  return entries
    .map((entry) => ({ label: entryLabel(entry), value: entry[key] }))
    .sort((a, b) => b.value - a.value || a.label.localeCompare(b.label, "es"));
}
