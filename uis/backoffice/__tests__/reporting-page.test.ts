import { createElement } from "react";
import { render, screen, waitFor, within } from "@testing-library/react";

// Respuesta real de GET /reporting/weekly-warehouse-client-performance contra el Supabase del
// proyecto (10 de noviembre de 2026).
const REAL_REPORT = {
  week_start: "2026-11-02",
  computed_at: "2026-11-10T15:57:06Z",
  entries: [
    { warehouse: "los_angeles", client_id: "soundwave_electronics", inbound_units_count: 5, outbound_orders_count: 1,
      stockout_events_count: 0, discrepancy_events_count: 0, discrepancy_rate: 0.0 },
  ],
};

import { ReportingClient } from "../app/(protected)/reporting/reporting-client";

// La red se simula en fetch (como en auth.test.ts): el dashboard pasa por el backofficeFetch real,
// con el JWT de la sesión en localStorage.
const fetchMock = jest.fn<Promise<Response>, [string, RequestInit]>();

function sessionToken(): string {
  const payload = btoa(JSON.stringify({ sub: "ana", exp: Math.floor(Date.now() / 1000) + 3600 }));
  return `header.${payload}.signature`;
}

function respond(status: number, body: unknown) {
  return Promise.resolve({ ok: status < 400, status, json: () => Promise.resolve(body) } as unknown as Response);
}

function requestedPath(): string {
  return new URL(fetchMock.mock.calls[0][0], "http://api.test").pathname + new URL(fetchMock.mock.calls[0][0], "http://api.test").search;
}

beforeEach(() => {
  fetchMock.mockReset();
  global.fetch = fetchMock as unknown as typeof fetch;
  window.localStorage.setItem("trackflow.access_token", sessionToken());
  jest.useFakeTimers({ now: new Date("2026-11-10T09:00:00Z"), doNotFake: ["setTimeout", "setInterval", "queueMicrotask", "nextTick"] });
});

afterEach(() => jest.useRealTimers());

it("muestra cada KPI con su nombre del BRIEFING y el periodo que cubre", async () => {
  fetchMock.mockReturnValue(respond(200, REAL_REPORT));
  render(createElement(ReportingClient));

  await screen.findByText("Semana del 2 al 8 de noviembre de 2026");
  expect(requestedPath()).toBe("/reporting/weekly-warehouse-client-performance");
  expect(new Headers(fetchMock.mock.calls[0][1].headers).get("Authorization")).toMatch(/^Bearer /);
  expect(screen.getByText(/Datos actualizados el 10 de noviembre de 2026, 15:57 UTC/)).toBeTruthy();

  for (const name of ["Volumen de entrada", "Throughput de salida", "Frecuencia de quiebre de stock", "Tasa de discrepancia"]) {
    expect(screen.getByRole("heading", { name })).toBeTruthy();
  }
  const volume = screen.getByRole("region", { name: "Volumen de entrada" });
  expect(within(volume).getByText("Los Ángeles · Soundwave Electronics")).toBeTruthy();
  expect(within(volume).getByText("5")).toBeTruthy();
  const rate = screen.getByRole("region", { name: "Tasa de discrepancia" });
  expect(within(rate).getByText("0 %")).toBeTruthy();
  // Ningún identificador técnico a la vista.
  expect(screen.queryByText(/soundwave_electronics|los_angeles|inbound_units_count/)).toBeNull();
  expect(screen.queryByText(/todavía no está disponible/)).toBeNull();
});

it("avisa si la semana más reciente aún no se ha calculado", async () => {
  fetchMock.mockReturnValue(respond(200, { ...REAL_REPORT, week_start: "2026-10-26" }));
  render(createElement(ReportingClient));
  expect(await screen.findByText(/semana del 2 al 8 de noviembre de 2026 todavía no está disponible/)).toBeTruthy();
});

it("una semana sin datos se muestra como tal, no como un error", async () => {
  fetchMock.mockReturnValue(respond(404, { detail: "Todavía no hay ninguna semana calculada" }));
  render(createElement(ReportingClient));
  await waitFor(() => expect(screen.getByText("Todavía no hay ninguna semana calculada.")).toBeTruthy());
  expect(screen.queryByRole("heading", { name: "Volumen de entrada" })).toBeNull();
});
