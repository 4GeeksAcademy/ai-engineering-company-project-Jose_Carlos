import {
  KPIS,
  WeeklyPerformanceEntry,
  clientLabel,
  entryLabel,
  formatKpi,
  formatRate,
  formatUpdatedAt,
  formatWeek,
  kpiBars,
  lastClosedWeek,
  shiftWeek,
  weekTotals,
} from "../app/lib/reporting";

const entries: WeeklyPerformanceEntry[] = [
  { warehouse: "los_angeles", client_id: "glowlab_cosmetics", inbound_units_count: 80, outbound_orders_count: 2,
    stockout_events_count: 0, discrepancy_events_count: 0, discrepancy_rate: 0 },
  { warehouse: "los_angeles", client_id: "purestep_footwear", inbound_units_count: 420, outbound_orders_count: 4,
    stockout_events_count: 1, discrepancy_events_count: 1, discrepancy_rate: 0.25 },
  { warehouse: "zaragoza", client_id: "purestep_footwear", inbound_units_count: 50, outbound_orders_count: 0,
    stockout_events_count: 0, discrepancy_events_count: 1, discrepancy_rate: 0 },
];

describe("los KPIs llevan el nombre del BRIEFING", () => {
  it("son los cuatro de «KPIs a medir», en orden", () => {
    expect(KPIS.map((kpi) => kpi.name)).toEqual([
      "Volumen de entrada", "Throughput de salida", "Frecuencia de quiebre de stock", "Tasa de discrepancia",
    ]);
  });
});

describe("periodo del reporte", () => {
  it("muestra la semana de lunes a domingo", () => {
    expect(formatWeek("2026-11-02")).toBe("Semana del 2 al 8 de noviembre de 2026");
    expect(formatWeek("2026-10-26")).toBe("Semana del 26 de octubre al 1 de noviembre de 2026");
    expect(formatWeek("2026-12-28")).toBe("Semana del 28 de diciembre de 2026 al 3 de enero de 2027");
  });

  it("navega de semana en semana", () => {
    expect(shiftWeek("2026-11-02", -1)).toBe("2026-10-26");
    expect(shiftWeek("2026-12-28", 1)).toBe("2027-01-04");
  });

  it("la última semana cerrada es la anterior al lunes de hoy (UTC)", () => {
    expect(lastClosedWeek(new Date("2026-11-10T09:00:00Z"))).toBe("2026-11-02");   // martes
    expect(lastClosedWeek(new Date("2026-11-09T00:00:00Z"))).toBe("2026-11-02");   // lunes
    expect(lastClosedWeek(new Date("2026-11-08T23:59:59Z"))).toBe("2026-10-26");   // domingo
  });

  it("dice cuándo se calcularon los datos", () => {
    expect(formatUpdatedAt("2026-11-09T18:49:34Z")).toBe("9 de noviembre de 2026, 18:49 UTC");
    expect(formatUpdatedAt(null)).toBe("fecha no disponible");
  });
});

describe("etiquetas legibles", () => {
  it("nombra almacenes y clientes sin identificadores técnicos", () => {
    expect(clientLabel("soundwave_electronics")).toBe("Soundwave Electronics");
    expect(entryLabel(entries[2])).toBe("Zaragoza · Purestep Footwear");
  });

  it("la tasa de discrepancia se muestra como porcentaje", () => {
    expect(formatRate(0.25)).toBe("25 %");
    expect(formatRate(0)).toBe("0 %");
    expect(formatRate(0.0033)).toBe("0,33 %");
    expect(formatKpi("inbound_units_count", 4200)).toBe("4200");
    expect(formatKpi("discrepancy_rate", 0.002)).toBe("0,20 %");
  });
});

describe("totales de la semana", () => {
  it("suma los conteos y recalcula la tasa con su definición", () => {
    // 2 discrepancias / 6 pedidos de salida = 0,3333 (no la media de las tasas de cada fila).
    expect(weekTotals(entries)).toEqual({
      inbound_units_count: 550, outbound_orders_count: 6, stockout_events_count: 1, discrepancy_rate: 0.3333,
    });
    expect(weekTotals([]).discrepancy_rate).toBe(0);
  });

  it("ordena las barras de cada KPI de mayor a menor", () => {
    expect(kpiBars(entries, "inbound_units_count").map((bar) => bar.label)).toEqual([
      "Los Ángeles · Purestep Footwear", "Los Ángeles · Glowlab Cosmetics", "Zaragoza · Purestep Footwear",
    ]);
  });
});
