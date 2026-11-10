"use client";

import { ReactNode, useState } from "react";
import { errorMessage } from "../../lib/inventory";
import {
  KPIS,
  KpiKey,
  NoReportForWeek,
  WAREHOUSE_LABELS,
  WeeklyPerformanceReport,
  clientLabel,
  formatKpi,
  formatUpdatedAt,
  formatWeek,
  getWeeklyPerformance,
  kpiBars,
  lastClosedWeek,
  shiftWeek,
  weekTotals,
} from "../../lib/reporting";
import { useApiResource } from "../../lib/use-api-resource";
import { Alert, AlertState, REFRESH_BUTTON_CLASS } from "../../ui/inventory-ui";

// Reporte Semanal de Desempeño por Almacén y Cliente (BRIEFING del pipeline): la vista de dirección
// (Thomas, CEO; Ana, Head of Warehouse Operations). Lee GET /reporting/weekly-warehouse-client-performance,
// que sirve las filas de reporting.weekly_warehouse_client_performance. Sin jerga técnica.

const EMPTY: WeeklyPerformanceReport | null = null;

/** Barras horizontales: el valor va escrito al lado, así que no depende del color. */
function BarList({ kpi, bars }: { kpi: KpiKey; bars: { label: string; value: number }[] }) {
  const max = Math.max(...bars.map((bar) => bar.value), 0);
  return (
    <ul className="space-y-2">
      {bars.map((bar) => (
        <li key={bar.label} className="grid grid-cols-[minmax(9rem,15rem)_1fr_auto] items-center gap-3 text-sm">
          <span className="truncate text-slate-700" title={bar.label}>{bar.label}</span>
          <span className="h-3 rounded-r bg-slate-100">
            <span className="block h-3 rounded-r bg-cyan-700" style={{ width: `${max ? (bar.value / max) * 100 : 0}%` }} />
          </span>
          <span className="min-w-16 text-right font-semibold tabular-nums text-slate-900">{formatKpi(kpi, bar.value)}</span>
        </li>
      ))}
    </ul>
  );
}

function KpiCard({ name, value, unit }: { name: string; value: string; unit: string }) {
  return (
    <div className="rounded-2xl border border-cyan-200 bg-white p-4 shadow-sm">
      <p className="text-sm font-semibold text-slate-600">{name}</p>
      <p className="mt-1 text-3xl font-black tabular-nums text-slate-900">{value}</p>
      <p className="text-xs text-slate-500">{unit} · total de la semana</p>
    </div>
  );
}

function Panel({ id, title, children, subtitle }: { id: string; title: string; subtitle: string; children: ReactNode }) {
  return (
    <section aria-labelledby={id} className="rounded-2xl border border-cyan-200 bg-white p-5 shadow-sm md:p-6">
      <h2 id={id} className="text-lg font-bold text-slate-900">{title}</h2>
      <p className="mb-4 mt-1 text-sm text-slate-600">{subtitle}</p>
      {children}
    </section>
  );
}

export function ReportingClient() {
  const [alert, setAlert] = useState<AlertState>(null);
  const [week, setWeek] = useState("");          // "" = la semana más reciente calculada
  const [missing, setMissing] = useState<string | null>(null);
  const { data: report, setData, loading, reload } = useApiResource(() => getWeeklyPerformance(week), EMPTY, {
    key: week,
    onLoaded: () => {
      setAlert(null);
      setMissing(null);
    },
    onError: (error) => {
      if (error instanceof NoReportForWeek) {
        setData(null);
        setAlert(null);
        setMissing(error.message);
        return;
      }
      setAlert({ type: "error", message: `No se pudo cargar el reporte. ${errorMessage(error)}` });
    },
  });

  const shownWeek = report?.week_start ?? week;
  const latestClosed = lastClosedWeek(new Date());
  const totals = report ? weekTotals(report.entries) : null;
  const stale = report && !week && report.week_start < latestClosed;

  function go(weeks: number) {
    if (shownWeek) setWeek(shiftWeek(shownWeek, weeks));
  }

  return (
    <main className="mx-auto w-full max-w-6xl px-4 py-8 md:px-6 md:py-10">
      <section aria-labelledby="page-title">
        <p className="mb-2 text-sm font-bold uppercase tracking-widest text-cyan-700">Dirección · Reporte semanal</p>
        <h1 id="page-title" className="text-3xl font-black tracking-tight text-slate-900 md:text-4xl">
          Desempeño por almacén y cliente
        </h1>
        <p className="mt-3 max-w-3xl text-slate-600">
          Cómo ha funcionado cada almacén para cada cliente en la semana: mercancía recibida, pedidos despachados, avisos de
          stock bajo y precisión del inventario. Se actualiza solo cada lunes por la mañana con la semana que acaba de terminar.
        </p>
      </section>

      <nav aria-label="Semana del reporte" className="mt-6 flex flex-wrap items-center gap-3 rounded-2xl border border-cyan-200 bg-white p-4 shadow-sm">
        <button type="button" className={REFRESH_BUTTON_CLASS} disabled={loading || !shownWeek} onClick={() => go(-1)}>
          ← Semana anterior
        </button>
        <div className="min-w-0 flex-1 text-center">
          <p data-testid="report-period" className="text-lg font-bold text-slate-900">
            {shownWeek ? formatWeek(shownWeek) : loading ? "Cargando…" : "Sin semana"}
          </p>
          {report && <p className="text-xs text-slate-500">Datos actualizados el {formatUpdatedAt(report.computed_at)}</p>}
        </div>
        <button
          type="button"
          className={REFRESH_BUTTON_CLASS}
          disabled={loading || !shownWeek || shownWeek >= latestClosed}
          onClick={() => go(1)}
        >
          Semana siguiente →
        </button>
        {week && (
          <button type="button" className={REFRESH_BUTTON_CLASS} disabled={loading} onClick={() => setWeek("")}>
            Ir a la más reciente
          </button>
        )}
        <button type="button" className={REFRESH_BUTTON_CLASS} disabled={loading} onClick={reload}>Actualizar</button>
      </nav>

      <Alert id="reporting-alert" alert={alert} wrapperClass="mt-4" />
      {stale && (
        <Alert
          id="reporting-stale"
          wrapperClass="mt-4"
          role="status"
          alert={{
            type: "warning",
            message: `El reporte de la ${formatWeek(latestClosed).toLowerCase()} todavía no está disponible. Se muestra la última semana calculada.`,
          }}
        />
      )}
      {missing && (
        <p className="mt-6 rounded-2xl border border-slate-200 bg-white p-6 text-center text-slate-600" role="status">
          {missing}
        </p>
      )}

      {report && totals && (
        <>
          <section aria-label="Resumen de la semana" className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {KPIS.map((kpi) => (
              <KpiCard key={kpi.key} name={kpi.name} value={formatKpi(kpi.key, totals[kpi.key])} unit={kpi.unit} />
            ))}
          </section>

          <div className="mt-6 grid gap-6 lg:grid-cols-2">
            {KPIS.map((kpi) => (
              <Panel key={kpi.key} id={`kpi-${kpi.key}`} title={kpi.name} subtitle={kpi.measures}>
                <BarList kpi={kpi.key} bars={kpiBars(report.entries, kpi.key)} />
              </Panel>
            ))}
          </div>

          <div className="mt-6">
            <Panel id="detail-title" title="Detalle por almacén y cliente" subtitle="Las mismas cifras en una tabla, una fila por almacén y cliente.">
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-500">
                    <tr>
                      <th className="px-2 py-2 font-semibold">Almacén</th>
                      <th className="px-2 py-2 font-semibold">Cliente</th>
                      {KPIS.map((kpi) => <th key={kpi.key} className="px-2 py-2 text-right font-semibold">{kpi.name}</th>)}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 tabular-nums text-slate-700">
                    {report.entries.map((entry) => (
                      <tr key={`${entry.warehouse}-${entry.client_id}`}>
                        <td className="whitespace-nowrap px-2 py-1.5">{WAREHOUSE_LABELS[entry.warehouse] ?? entry.warehouse}</td>
                        <td className="whitespace-nowrap px-2 py-1.5">{clientLabel(entry.client_id)}</td>
                        {KPIS.map((kpi) => (
                          <td key={kpi.key} className="whitespace-nowrap px-2 py-1.5 text-right">{formatKpi(kpi.key, entry[kpi.key])}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="mt-3 text-xs text-slate-500">
                Tasa de discrepancia = pedidos de salida con una discrepancia de inventario ÷ pedidos de salida de la semana (0 % si
                no hubo salidas). Semanas de lunes a domingo, hora UTC.
              </p>
            </Panel>
          </div>
        </>
      )}
    </main>
  );
}
