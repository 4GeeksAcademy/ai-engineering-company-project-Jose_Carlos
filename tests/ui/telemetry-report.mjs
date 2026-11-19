// Dashboard de salud del sistema (hito 17): /telemetry del backoffice consume GET /telemetry/report.
//
// Arranca la API (SQLite desechable, nunca Supabase) y el backoffice, guarda un lote de eventos
// conocido por POST /telemetry/events (más un login real, que emite user_logged_in) y comprueba que
// la página muestra el periodo y una sección por métrica con las cifras que calcula el pipeline.
//
// Con TELEMETRY_REPORT_SCREENSHOT=<ruta.png> guarda además una captura de la página (fuera del repo).

import fs from "node:fs";
import { randomUUID } from "node:crypto";
import { PAGE_HELPERS, Recorder, killTree, launchChrome, makeTempDir, openPage, removeDir, waitExit, waitFor } from "./lib/harness.mjs";
import { apiCall, createUser, signIn, startStack } from "./lib/backoffice-app.mjs";

const EMAIL = "telemetria-report-ui@trackflow.com";
const PASSWORD = "telemetria-report-1234";

function event(event_type, properties, minutesAgo = 5) {
  return {
    eventId: randomUUID(),
    timestamp: new Date(Date.now() - minutesAgo * 60000).toISOString(),
    sessionId: randomUUID(),
    userId: null,
    event_type,
    schemaVersion: event_type === "login_failed" ? "2.0.0" : "1.0.0",
    requestId: randomUUID(),
    source: "backoffice_web",
    environment: "development",
    properties,
  };
}

const pageView = () => event("page_viewed", { page_route: "/inventory/products", section: "inventory", previous_route: null });
const pageLoad = (ttfb, lcp) => event("page_load_recorded", {
  page_route: "/inventory/products", device_class: "desktop", navigation_type: "navigate",
  ttfb_ms: ttfb, fcp_ms: ttfb + 200, lcp_ms: lcp, inp_ms: null, cls: 0,
});

const BATCH = [
  ...Array.from({ length: 6 }, pageView),
  pageLoad(120, 1800),
  pageLoad(180, 2600),
  event("login_failed", { failure_reason: "invalid_credentials" }),
  event("api_request_failed", { api_route: "/inventory/products", http_method: "GET", failure_kind: "timeout", status_code: null }),
];

export async function run({ repoRoot }) {
  const rec = new Recorder("telemetry-report");
  const apiTemp = makeTempDir("telemetry-report-api");
  const browser = await launchChrome();
  let stack = null;
  let cleanup = {};

  try {
    stack = await startStack(repoRoot, apiTemp);
    const { api, app: web } = stack;
    const { token } = await createUser(api.origin, EMAIL, PASSWORD); // su login emite user_logged_in
    const receipt = await apiCall(api.origin, "POST", "/telemetry/events", { body: { events: BATCH } });
    rec.check("TR-1", "the known batch is stored (10 events, none rejected)", receipt.stored === BATCH.length && receipt.rejected === 0, receipt);

    const report = await apiCall(api.origin, "GET", "/telemetry/report", { token });
    rec.check("TR-2", "GET /telemetry/report answers {period, metrics} with the 7-day default window",
      report.period && report.metrics && new Date(report.period.to) - new Date(report.period.from) === 7 * 86400000, report.period);

    const policy = ({ url }) => url.hostname === "127.0.0.1";
    const page = await openPage(browser, { policy });
    const run = (expression) => page.eval(`(()=>{${PAGE_HELPERS}return ${expression}})()`);
    await signIn(page, web.origin, token);
    await page.goto(`${web.origin}/telemetry`, 120000);
    const ready = await waitFor(() => run(`(q('[data-testid=report-period]')?.textContent||'').includes('Periodo')`), 60000);

    const view = await run(`({
      period: q('[data-testid=report-period]')?.textContent || '',
      headings: qa('main h2').map((h) => h.textContent),
      text: q('main')?.innerText || '',
      bars: qa('main ul[aria-label] li').length,
    })`);

    rec.check("TR-3", "the page shows the period (from → to, UTC) being displayed", ready && /Periodo: .*UTC.*→.*UTC/.test(view.period), view.period);
    rec.check("TR-4", "one section per metric: volume, event types, error rate, login failures, page-load latency",
      ["Volumen por día", "Tipos de evento dominantes", "Tasa de errores por tipo", "Fallos de login", "Latencia de carga por ruta"].every((h) => view.headings.includes(h)),
      view.headings);
    rec.check("TR-5", "the numbers are the pipeline's: 11 events today, api_request_failed at 9.1 %, 1 of 2 logins failed (50.0 %)",
      /page_viewed\s+6/.test(view.text) && /api_request_failed\s+1\s+1\s+11\s+9\.1 %/.test(view.text) && /2\s+1\s+1\s+50\.0 %/.test(view.text),
      view.text.slice(0, 600));
    rec.check("TR-6", "latency table shows TTFB/LCP percentiles for /inventory/products and the charts render bars",
      /\/inventory\/products\s+2\s+150 ms/.test(view.text) && view.bars >= 4, { bars: view.bars });

    if (process.env.TELEMETRY_REPORT_SCREENSHOT) {
      const { contentSize } = await page.send("Page.getLayoutMetrics", {});
      const shot = await page.send("Page.captureScreenshot", {
        format: "png", captureBeyondViewport: true, clip: { x: 0, y: 0, width: 1280, height: Math.ceil(contentSize.height), scale: 1 },
      });
      fs.writeFileSync(process.env.TELEMETRY_REPORT_SCREENSHOT, Buffer.from(shot.data, "base64"));
    }
    rec.check("TR-NET", "no request left 127.0.0.1; nothing blocked", page.state.blocked.length === 0, page.state.blocked);
    await page.close();
  } catch (error) {
    rec.abort(error);
  } finally {
    cleanup = await browser.close();
    if (stack) {
      killTree(stack.app.proc);
      killTree(stack.api.proc);
      cleanup.nextStopped = await waitExit(stack.app.proc, 8000);
      cleanup.apiStopped = await waitExit(stack.api.proc, 8000);
    }
  }
  cleanup.apiTempRemoved = removeDir(apiTemp);
  rec.check("TR-CLEAN", "uvicorn and next dev stopped; Chrome profile and the disposable TinyDB/SQLite removed",
    cleanup.profileRemoved && cleanup.apiTempRemoved && (stack ? cleanup.apiStopped && cleanup.nextStopped : true), cleanup);
  return rec;
}
