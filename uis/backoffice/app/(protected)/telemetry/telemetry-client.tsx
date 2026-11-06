"use client";

import { FormEvent, ReactNode, useState } from "react";
import { errorMessage } from "../../lib/inventory";
import {
  TelemetryReport,
  eventsByDay,
  eventsByTypeInPeriod,
  formatMs,
  formatPercent,
  formatUtc,
  getTelemetryReport,
} from "../../lib/telemetry-report";
import { useApiResource } from "../../lib/use-api-resource";
import { Alert, AlertState, INPUT_CLASS, REFRESH_BUTTON_CLASS } from "../../ui/inventory-ui";

// Salud del sistema — GET /telemetry/report. Vista técnica para ingeniería: volumen, composición,
// errores, latencia de carga y fallos de login. Sin métricas de negocio.

const EMPTY: TelemetryReport | null = null;

type Bar = { label: string; value: number };

/** Barras horizontales de una sola serie; el valor va escrito, así que no depende del color. */
function BarList({ bars, format = String, label }: { bars: Bar[]; format?: (value: number) => string; label: string }) {
  const max = Math.max(...bars.map((bar) => bar.value), 0);
  if (bars.length === 0) return <Empty />;
  return (
    <ul aria-label={label} className="space-y-1.5">
      {bars.map((bar) => (
        <li key={bar.label} className="grid grid-cols-[minmax(8rem,14rem)_1fr_auto] items-center gap-3 text-sm" title={`${bar.label}: ${format(bar.value)}`}>
          <span className="truncate font-mono text-xs text-slate-700">{bar.label}</span>
          <span className="h-3 rounded-r bg-slate-100">
            <span className="block h-3 rounded-r bg-cyan-700" style={{ width: `${max ? (bar.value / max) * 100 : 0}%` }} />
          </span>
          <span className="tabular-nums text-slate-700">{format(bar.value)}</span>
        </li>
      ))}
    </ul>
  );
}

function Empty() {
  return <p className="text-sm text-slate-500">Sin datos en este periodo.</p>;
}

function Table({ head, rows }: { head: string[]; rows: ReactNode[][] }) {
  if (rows.length === 0) return <Empty />;
  return (
    <div className="mt-4 overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-500">
          <tr>{head.map((cell) => <th key={cell} className="px-2 py-2 font-semibold">{cell}</th>)}</tr>
        </thead>
        <tbody className="divide-y divide-slate-100 tabular-nums text-slate-700">
          {rows.map((cells, index) => (
            <tr key={index}>{cells.map((cell, column) => <td key={column} className="whitespace-nowrap px-2 py-1.5">{cell}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Panel({ id, title, question, children }: { id: string; title: string; question: string; children: ReactNode }) {
  return (
    <section aria-labelledby={id} className="rounded-2xl border border-cyan-200 bg-white p-5 shadow-sm md:p-6">
      <h2 id={id} className="text-lg font-bold text-slate-900">{title}</h2>
      <p className="mb-4 mt-1 text-sm text-slate-600">{question}</p>
      {children}
    </section>
  );
}

export function TelemetryClient() {
  const [alert, setAlert] = useState<AlertState>(null);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [query, setQuery] = useState({ from: "", to: "" });
  const { data: report, loading, reload } = useApiResource(() => getTelemetryReport(query.from, query.to), EMPTY, {
    key: `${query.from}|${query.to}`,
    onLoaded: () => setAlert(null),
    onError: (error) => setAlert({ type: "error", message: `No se pudo cargar el reporte. ${errorMessage(error)}` }),
  });

  function apply(event: FormEvent) {
    event.preventDefault();
    setQuery({ from, to });
  }

  const metrics = report?.metrics;

  return (
    <main className="mx-auto w-full max-w-6xl px-4 py-8 md:px-6 md:py-10">
      <section aria-labelledby="page-title">
        <p className="mb-2 text-sm font-bold uppercase tracking-widest text-cyan-700">Ingeniería · Telemetría</p>
        <h1 id="page-title" className="text-3xl font-black tracking-tight text-slate-900 md:text-4xl">Salud del sistema</h1>
        <p className="mt-3 max-w-3xl text-slate-600">
          Métricas operacionales calculadas a partir de los eventos de telemetría guardados. Todos los días son días UTC; la API
          recalcula el reporte como mucho una vez por minuto.
        </p>
      </section>

      <form onSubmit={apply} className="mt-6 flex flex-wrap items-end gap-3 rounded-2xl border border-cyan-200 bg-white p-4 shadow-sm">
        <label className="text-sm font-semibold text-slate-700">
          Desde (UTC)
          <input type="date" value={from} onChange={(event) => setFrom(event.target.value)} className={INPUT_CLASS} />
        </label>
        <label className="text-sm font-semibold text-slate-700">
          Hasta (UTC, incluido)
          <input type="date" value={to} onChange={(event) => setTo(event.target.value)} className={INPUT_CLASS} />
        </label>
        <button type="submit" className={REFRESH_BUTTON_CLASS} disabled={loading}>Aplicar</button>
        <button type="button" className={REFRESH_BUTTON_CLASS} disabled={loading} onClick={reload}>Actualizar</button>
        <p className="text-xs text-slate-500">Vacío = últimos 7 días.</p>
        <p data-testid="report-period" className="ml-auto rounded-lg bg-cyan-50 px-3 py-2 text-sm text-cyan-900">
          {report ? (
            <>Periodo: <strong>{formatUtc(report.period.from)}</strong> → <strong>{formatUtc(report.period.to)}</strong></>
          ) : loading ? "Cargando…" : "Sin periodo"}
        </p>
      </form>

      <Alert id="telemetry-alert" alert={alert} wrapperClass="mt-4" />

      {metrics && (
        <div className="mt-6 grid gap-6 lg:grid-cols-2">
          <Panel id="volume-title" title="Volumen por día" question="¿Llega telemetría de la API y del backoffice cada día?">
            <BarList label="Eventos por día" bars={eventsByDay(metrics.events_per_day)} />
            <Table
              head={["Día", "Origen", "Eventos"]}
              rows={metrics.events_per_day.map((row) => [row.date, row.source, row.events])}
            />
          </Panel>

          <Panel id="types-title" title="Tipos de evento dominantes" question="¿Qué tipos concentran el volumen del periodo?">
            <BarList label="Eventos por tipo" bars={eventsByTypeInPeriod(metrics.events_by_type).slice(0, 10)} />
            <Table
              head={["Día", "Tipo", "Eventos", "% del día"]}
              rows={metrics.events_by_type.map((row) => [row.date, row.event_type, row.events, formatPercent(row.share)])}
            />
          </Panel>

          <Panel id="errors-title" title="Tasa de errores por tipo" question="Errores del sistema sobre el total de eventos de cada día.">
            <BarList
              label="Tasa de error por día y tipo"
              bars={metrics.error_rate_by_type.map((row) => ({ label: `${row.date} · ${row.event_type}`, value: row.error_rate }))}
              format={formatPercent}
            />
            <Table
              head={["Día", "Tipo", "Eventos", "Ocurrencias", "Total día", "Tasa"]}
              rows={metrics.error_rate_by_type.map((row) => [
                row.date, row.event_type, row.errors, row.occurrences, row.total_events, formatPercent(row.error_rate),
              ])}
            />
          </Panel>

          <Panel id="auth-title" title="Fallos de login" question="login_failed / (login_failed + user_logged_in) por día.">
            <BarList
              label="Tasa de fallos de login por día"
              bars={metrics.auth_failure_rate.map((row) => ({ label: row.date, value: row.failure_rate }))}
              format={formatPercent}
            />
            <Table
              head={["Día", "Intentos", "Fallidos", "Correctos", "Tasa de fallo"]}
              rows={metrics.auth_failure_rate.map((row) => [row.date, row.attempts, row.failed, row.succeeded, formatPercent(row.failure_rate)])}
            />
          </Panel>

          <div className="lg:col-span-2">
            <Panel id="latency-title" title="Latencia de carga por ruta" question="Percentiles de TTFB y LCP del backoffice (LCP bueno: ≤ 2500 ms).">
              <BarList
                label="LCP p95 por día y ruta"
                bars={metrics.page_load_latency
                  .filter((row) => row.lcp_p95_ms !== null)
                  .map((row) => ({ label: `${row.date} · ${row.page_route}`, value: row.lcp_p95_ms as number }))}
                format={(value) => formatMs(value)}
              />
              <Table
                head={["Día", "Ruta", "Muestras", "TTFB p50", "TTFB p95", "LCP p50", "LCP p95"]}
                rows={metrics.page_load_latency.map((row) => [
                  row.date, row.page_route, row.samples,
                  formatMs(row.ttfb_p50_ms), formatMs(row.ttfb_p95_ms), formatMs(row.lcp_p50_ms), formatMs(row.lcp_p95_ms),
                ])}
              />
            </Panel>
          </div>
        </div>
      )}
    </main>
  );
}
