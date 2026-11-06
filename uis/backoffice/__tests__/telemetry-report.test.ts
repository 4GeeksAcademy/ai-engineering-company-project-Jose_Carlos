import { eventsByDay, eventsByTypeInPeriod, formatMs, formatPercent, formatUtc, reportQuery } from "../app/lib/telemetry-report";

describe("reportQuery", () => {
  it("sin fechas deja que la API use los últimos 7 días", () => {
    expect(reportQuery("", "")).toBe("");
  });

  it("'hasta' es inclusivo en pantalla y exclusivo en la API (00:00 UTC del día siguiente)", () => {
    expect(reportQuery("2026-11-01", "2026-11-07")).toBe("?start_date=2026-11-01T00%3A00%3A00Z&end_date=2026-11-08T00%3A00%3A00Z");
    expect(reportQuery("", "2026-12-31")).toBe("?end_date=2027-01-01T00%3A00%3A00Z");
  });
});

describe("resúmenes para los gráficos", () => {
  it("suma los orígenes de cada día", () => {
    expect(eventsByDay([
      { date: "2026-11-02", source: "api", events: 1 },
      { date: "2026-11-02", source: "backoffice_web", events: 2 },
      { date: "2026-11-03", source: "api", events: 4 },
    ])).toEqual([{ label: "2026-11-02", value: 3 }, { label: "2026-11-03", value: 4 }]);
  });

  it("ordena los tipos por volumen del periodo", () => {
    expect(eventsByTypeInPeriod([
      { date: "2026-11-02", event_type: "login_failed", events: 1, share: 0.5 },
      { date: "2026-11-02", event_type: "page_viewed", events: 1, share: 0.5 },
      { date: "2026-11-03", event_type: "page_viewed", events: 2, share: 1 },
    ])).toEqual([{ label: "page_viewed", value: 3 }, { label: "login_failed", value: 1 }]);
  });
});

describe("formatos", () => {
  it("porcentajes, milisegundos y fechas UTC", () => {
    expect(formatPercent(0.0526)).toBe("5.3 %");
    expect(formatPercent(0.0004)).toBe("0.04 %");
    expect(formatMs(null)).toBe("—");
    expect(formatUtc("2026-11-01T00:00:00Z")).toBe("01/11/2026 00:00 UTC");
  });
});
