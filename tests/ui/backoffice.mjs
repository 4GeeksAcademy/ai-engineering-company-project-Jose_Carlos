// Backoffice baseline (BP-3) — derived from audit R4-C3 online_render_checks.mjs (render),
// R4-B backoffice_api_unavailable.mjs (error path) and the mounted FastAPI mode (U-A4 reference).
//
// Modes:
//   static-own-root : read-only static server rooted at uis/backoffice/  (page /index.html)
//   static-uis-root : read-only static server rooted at uis/             (page /backoffice/index.html)
//   mounted         : local uvicorn running services.api.main:app        (page /backoffice/)
//
// Only synthetic CSV content is uploaded, and only to 127.0.0.1. http://localhost:8000 is never
// contacted (blocked by the guard). uvicorn runs with TEMP/TMP/TMPDIR pointed at a disposable
// directory because /analyze leaves its temp copy behind (AS-IS), and without writing bytecode.

import fs from "node:fs";
import path from "node:path";
import { spawn } from "node:child_process";
import {
  PAGE_HELPERS, Recorder, freePort, groupSpawn, killTree, launchChrome, makeTempDir, openPage,
  removeDir, startStaticServer, track, waitExit, waitFor,
} from "./lib/harness.mjs";

const CDN = "cdn.tailwindcss.com";

// Same 5 synthetic rows as tests/test_api_characterization.py (3 valid, 2 invalid). No personal data.
const HEADER = "incident_id,date,country,customer_type,tracking_number,carrier,category,description,status,customer_email,satisfaction_score\n";
const SAMPLE_CSV = HEADER +
  "INC-1,2024-01-01,ES,B2C,TRK12345678,SEUR,LOST_PARCEL,Paquete perdido,CLOSED,a@b.com,4\n" +
  "INC-2,2024-01-02,US,B2B,TRK87654321,UPS,DAMAGE,Caja rota en entrega,OPEN,c@d.com,\n" +
  "INC-3,2024-01-03,ES,B2C,TRK11112222,MRW,LOST_PARCEL,Otro paquete perdido,CLOSED,e@f.com,5\n" +
  "INC-4,2024-01-04,FR,B2C,123,UPS,FOO,abc,WEIRD,bad,9\n" +
  ",2024-01-05,ES,B2C,TRK33334444,SEUR,DAMAGE,Golpe fuerte,CLOSED,g@h.com,\n";
const EXPECTED_EXPORT = "metric,value\r\nvalid_rows,3\r\ninvalid_rows,2\r\ncategory_LOST_PARCEL,2\r\ncategory_DAMAGE,1\r\n" +
  "status_CLOSED,2\r\nstatus_OPEN,1\r\naverage_satisfaction,4.50\r\n";

// Local: any method (the page under test only talks to its own origin). External: Tailwind CDN GET only.
const policy = ({ method, url }) =>
  url.hostname === "127.0.0.1" || (url.hostname === CDN && (method === "GET" || method === "HEAD"));

const RENDER_DOM = `(()=>{${PAGE_HELPERS}const fi=q('input[type=file]');return {
  title:document.title, tailwind:tailwindReady(), header:vis('header').visible, badge:{text:txt('header span'),visible:vis('header span').visible},
  h1:{text:txt('#page-title'),visible:vis('#page-title').visible}, form:vis('#analysisForm').visible,
  file_input:{present:!!fi,accept:fi?.getAttribute('accept'),name:fi?.getAttribute('name'),label_visible:fi?.labels?.[0]?vis(fi.labels[0]).visible:false},
  analyze:{text:txt('#analyzeButton'),disabled:q('#analyzeButton').disabled,visible:vis('#analyzeButton').visible},
  export_:{text:txt('#exportButton'),disabled:q('#exportButton').disabled,visible:vis('#exportButton').visible},
  results:{hidden_class:q('#resultsSection').classList.contains('hidden'),visible:vis('#resultsSection').visible},
  message:{hidden_class:q('#requestMessage').classList.contains('hidden'),visible:vis('#requestMessage').visible},
  metrics_visible:['#validCount','#invalidCount','#satisfactionAverage'].some(s=>vis(s).visible),
  selected_file_visible:vis('#selectedFile').visible, spinner_visible:vis('#loadingSpinner').visible,
  hidden_audit:hiddenAudit(), overflow:overflowX(),
  analyze_url:typeof ANALYZE_URL!=='undefined'?ANALYZE_URL:null, export_url:typeof EXPORT_URL!=='undefined'?EXPORT_URL:null,
  website_link:q('header a')?.getAttribute('href')}})()`;

const AFTER_SUBMIT = `(()=>{${PAGE_HELPERS}return {message:txt('#requestMessage'),message_visible:vis('#requestMessage').visible,
  error_style:q('#requestMessage').className.includes('text-red-800'),button_text:txt('#analyzeButtonText'),
  analyze_disabled:q('#analyzeButton').disabled,spinner_hidden:q('#loadingSpinner').classList.contains('hidden'),
  results_visible:vis('#resultsSection').visible,export_disabled:q('#exportButton').disabled}})()`;

const waitIdle = (page) => waitFor(async () => {
  const s = await page.eval(AFTER_SUBMIT);
  return s.button_text === "Analizar archivo" && s.message ? s : null;
}, 15000);

// Checks shared by every mode: initial render (R4-C3) + submit without file (R4-C3 interaction).
async function renderChecks(rec, p, page, { expectedAnalyzeUrl, quirkNote }) {
  await waitFor(() => page.eval(`(()=>{${PAGE_HELPERS}return tailwindReady()})()`), 20000);
  const d = await page.eval(RENDER_DOM);
  rec.check(`${p}-01`, "page loads with 0 uncaught exceptions; Tailwind runtime applied", page.state.exceptions.length === 0 && d.tailwind, { exceptions: page.state.exceptions, tailwind: d.tailwind });
  rec.check(`${p}-02`, "title, header with 'Backoffice' badge, h1 'Analizador de incidentes CSV' visible",
    d.title === "Analizador de incidentes | TrackFlow" && d.header && d.badge.visible && /backoffice/i.test(d.badge.text) && d.h1.visible && d.h1.text === "Analizador de incidentes CSV",
    { title: d.title, badge: d.badge, h1: d.h1 });
  rec.check(`${p}-03`, "form visible; file input accepts .csv, field name 'file', visible drop-zone label",
    d.form && d.file_input.present && d.file_input.accept === ".csv,text/csv" && d.file_input.name === "file" && d.file_input.label_visible, d.file_input);
  rec.check(`${p}-04`, "'Analizar archivo' and 'Descargar resultados CSV' visible and disabled before any file",
    d.analyze.visible && d.analyze.disabled && d.analyze.text === "Analizar archivo" && d.export_.visible && d.export_.disabled && d.export_.text === "Descargar resultados CSV",
    { analyze: d.analyze, export: d.export_ });
  rec.check(`${p}-05`, "hidden before analysis: results section, request message, metrics, selected file, spinner",
    d.results.hidden_class && !d.results.visible && d.message.hidden_class && !d.message.visible && !d.metrics_visible && !d.selected_file_visible && !d.spinner_visible,
    { results: d.results, message: d.message, metrics_visible: d.metrics_visible, selected_file_visible: d.selected_file_visible, spinner_visible: d.spinner_visible });
  rec.check(`${p}-06`, "every .hidden element computes to display:none", d.hidden_audit.computed_display_none === d.hidden_audit.hidden_class_elements, d.hidden_audit);
  rec.check(`${p}-07`, "no horizontal overflow at 1280px", d.overflow === 0, { overflow_px: d.overflow });
  rec.check(`${p}-08`, `ANALYZE_URL resolves to ${expectedAnalyzeUrl} (${quirkNote})`, d.analyze_url === expectedAnalyzeUrl, { analyze_url: d.analyze_url, export_url: d.export_url }, "as-is-quirk");

  const reqsBefore = page.state.requests.length + page.state.blocked.length;
  await page.eval(`document.querySelector('#analysisForm').requestSubmit();true`);
  const nf = await waitFor(async () => { const s = await page.eval(AFTER_SUBMIT); return s.message ? s : null; }, 3000);
  rec.check(`${p}-09`, "submit without file shows the error message on screen and sends no request",
    nf?.message === "Selecciona un archivo CSV antes de iniciar el análisis." && nf.message_visible && nf.error_style &&
      page.state.requests.length + page.state.blocked.length === reqsBefore, nf);
  return d;
}

async function selectFile(rec, p, page, file) {
  await page.setFile("#csvFile", file);
  const s = await waitFor(() => page.eval(`(()=>{${PAGE_HELPERS}return vis('#selectedFile').visible?{name:txt('#fileName'),size:txt('#fileSize'),analyze_disabled:q('#analyzeButton').disabled,message_hidden:q('#requestMessage').classList.contains('hidden')}:null})()`), 3000);
  rec.check(`${p}-10`, "selecting a file shows its name/size, enables 'Analizar archivo' and clears the message",
    s?.name === path.basename(file) && !!s.size && !s.analyze_disabled && s.message_hidden, s);
}

const linkStatus = (page) => page.eval(`fetch(new URL(document.querySelector('header a').getAttribute('href'),location.href),{method:'HEAD'}).then(r=>r.status)`);

async function staticMode(rec, browser, { prefix, root, pagePath, expectedAnalyzeUrl, quirkNote, csvFile }) {
  const server = await startStaticServer(root);
  try {
    const page = await openPage(browser, { policy });
    const nav = await page.goto(server.origin + pagePath);
    rec.check(`${prefix}-00`, "page loads (load event, no navigation error)", nav.loaded && !nav.navigationError, nav);
    await renderChecks(rec, prefix, page, { expectedAnalyzeUrl, quirkNote });
    await selectFile(rec, prefix, page, csvFile);
    await page.eval(`document.querySelector('#analysisForm').requestSubmit();true`);
    const r = await waitIdle(page);
    return { server, page, afterSubmit: r };
  } catch (e) {
    await server.close();
    throw e;
  }
}

async function startApi(repoRoot, apiTemp) {
  const python = process.env.PYTHON || [path.join(repoRoot, ".venv", "Scripts", "python.exe"), path.join(repoRoot, ".venv", "bin", "python")].find((p) => fs.existsSync(p));
  if (!python) throw new Error("Project virtualenv not found: run `uv sync --frozen` first (or set PYTHON).");
  const port = await freePort();
  const output = [];
  const proc = track(spawn(python, ["-m", "uvicorn", "services.api.main:app", "--host", "127.0.0.1", "--port", String(port)], {
    cwd: repoRoot,
    env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1", TEMP: apiTemp, TMP: apiTemp, TMPDIR: apiTemp, TINYDB_PATH: path.join(apiTemp, "db.json") },
    stdio: ["ignore", "pipe", "pipe"],
    ...groupSpawn,
  }));
  for (const s of [proc.stdout, proc.stderr]) s.on("data", (b) => { output.push(String(b)); if (output.length > 200) output.shift(); });
  const origin = `http://127.0.0.1:${port}`;
  const ready = await waitFor(async () => (await fetch(origin + "/")).status === 200, 30000, 250);
  if (!ready) {
    killTree(proc);
    throw new Error("uvicorn did not become ready: " + output.join("").slice(-800));
  }
  return { proc, origin };
}

export async function run({ repoRoot }) {
  const rec = new Recorder("backoffice");
  const work = makeTempDir("backoffice");
  const apiTemp = makeTempDir("api-tmp");
  const csvFile = path.join(work, "synthetic-incidents.csv");
  const badFile = path.join(work, "synthetic-latin1.csv");
  fs.writeFileSync(csvFile, SAMPLE_CSV, "utf8");
  fs.writeFileSync(badFile, Buffer.from("incident_id\nñ\n", "latin1"));
  const uisRoot = path.join(repoRoot, "uis");
  const browser = await launchChrome({ allowedHosts: [CDN] });
  let api = null;
  let cleanup = {};
  try {
    // ---------------------------------------------------------- static, own root (R4-C3 + R4-B)
    {
      const { server, page, afterSubmit: r } = await staticMode(rec, browser, {
        prefix: "BO-OWN", root: path.join(uisRoot, "backoffice"), pagePath: "/index.html",
        expectedAnalyzeUrl: "http://localhost:8000/analyze", quirkNote: "hard-coded API host, F-15", csvFile,
      });
      const toApi = page.state.blocked.filter((b) => b.host === "localhost:8000");
      rec.check("BO-OWN-11", "API unreachable: POST to localhost:8000/analyze (blocked by guard) -> 'Failed to fetch' error shown",
        toApi.length === 1 && toApi[0].method === "POST" && toApi[0].path === "/analyze" &&
          r?.message === "No se pudo completar el análisis. Failed to fetch" && r.message_visible && r.error_style, { blocked: toApi, after: r });
      rec.check("BO-OWN-12", "after the API error: button restored, spinner hidden, results hidden, export disabled",
        r?.button_text === "Analizar archivo" && !r.analyze_disabled && r.spinner_hidden && !r.results_visible && r.export_disabled, r);
      const st = await linkStatus(page);
      rec.check("BO-OWN-13", "header link to the website resolves to 404 when uis/backoffice is the served root (FM-R4-003)", st === 404, { status: st }, "as-is-quirk");
      rec.check("BO-OWN-14", "nothing else left the machine (only the guarded localhost:8000 POST was blocked)",
        page.state.blocked.length === toApi.length && page.state.requests.every((x) => x.host.startsWith("127.0.0.1") || x.host === CDN), { blocked: page.state.blocked.length });
      await page.close();
      await server.close();
    }

    // ---------------------------------------------------------- static, uis/ root (R4-C3 + R4-B, FM-R4-005)
    {
      const { server, page, afterSubmit: r } = await staticMode(rec, browser, {
        prefix: "BO-UIS", root: uisRoot, pagePath: "/backoffice/index.html",
        expectedAnalyzeUrl: "/analyze", quirkNote: "path starts with /backoffice -> same-origin, F-15", csvFile,
      });
      const post = server.log.filter((l) => l.method === "POST");
      rec.check("BO-UIS-11", "POST /analyze goes to the static server (405) and the 405 error is shown on screen (FM-R4-005)",
        post.length === 1 && post[0].path === "/analyze" && post[0].status === 405 &&
          r?.message === "No se pudo completar el análisis. El servidor respondió con el estado 405." && r.error_style && !r.results_visible && r.export_disabled,
        { post, after: r }, "as-is-quirk");
      const st = await linkStatus(page);
      rec.check("BO-UIS-12", "header link to the website resolves (200) when uis/ is the served root", st === 200, { status: st });
      rec.check("BO-UIS-13", "no external request other than the Tailwind CDN; nothing blocked",
        page.state.blocked.length === 0 && page.state.requests.every((x) => x.host.startsWith("127.0.0.1") || x.host === CDN), { blocked: page.state.blocked });
      await page.close();
      await server.close();
    }

    // ---------------------------------------------------------- mounted in FastAPI (/backoffice/)
    {
      api = await startApi(repoRoot, apiTemp);
      const page = await openPage(browser, { policy });
      await page.send("Browser.setDownloadBehavior", { behavior: "deny" }).catch(() => {});
      await browser.send("Browser.setDownloadBehavior", { behavior: "deny" }).catch(() => {});
      const nav = await page.goto(api.origin + "/backoffice/");
      rec.check("BO-API-00", "/backoffice/ served by the API loads (load event, no navigation error)", nav.loaded && !nav.navigationError, nav);
      await renderChecks(rec, "BO-API", page, { expectedAnalyzeUrl: "/analyze", quirkNote: "same-origin in mounted mode" });

      // Error path: a non-UTF-8 file makes the API answer 500 text/plain; the UI must show it.
      await selectFile(rec, "BO-API-ERR", page, badFile);
      await page.eval(`document.querySelector('#analysisForm').requestSubmit();true`);
      const e = await waitIdle(page);
      rec.check("BO-API-11", "API 500 on a non-UTF-8 file is shown on screen; results stay hidden, export disabled",
        e?.message === "No se pudo completar el análisis. El servidor respondió con el estado 500." && e.error_style && !e.results_visible && e.export_disabled, e, "as-is-quirk");

      // Happy path: synthetic CSV -> results rendered.
      await selectFile(rec, "BO-API", page, csvFile);
      await page.eval(`document.querySelector('#analysisForm').requestSubmit();true`);
      const ok = await waitIdle(page);
      const analyzeResp = page.state.responses.filter((x) => x.path === "/analyze");
      rec.check("BO-API-12", "analysis POSTs to same-origin /analyze and gets 200 JSON",
        analyzeResp.length === 2 && analyzeResp[0].status === 500 && analyzeResp[1].status === 200 && analyzeResp[1].mimeType === "application/json", analyzeResp);
      rec.check("BO-API-13", "success message shown (invalid rows present), results visible, export enabled",
        ok?.message === "Análisis completado. Se encontraron registros que requieren revisión." && ok.message_visible && !ok.error_style && ok.results_visible && !ok.export_disabled, ok);
      const res = await page.eval(`(()=>{${PAGE_HELPERS}const rows=(id)=>qa(id+' > div').map(d=>[txt(d.querySelector('dt')),txt(d.querySelector('dd'))]);return {
        valid:txt('#validCount'),invalid:txt('#invalidCount'),satisfaction:txt('#satisfactionAverage'),file:txt('#resultsFileName'),
        categories:rows('#categoriesList'),statuses:rows('#statusesList'),invalid_status:txt('#invalidRecordsStatus'),
        invalid_records:qa('#invalidRecordsList article').map(a=>({title:txt(a.querySelector('h4')),errors:a.querySelectorAll('li').length}))}})()`);
      rec.check("BO-API-14", "metrics rendered: valid 3, invalid 2, satisfaction 4.50, file name",
        res.valid === "3" && res.invalid === "2" && res.satisfaction === "4.50" && res.file === "Archivo: synthetic-incidents.csv", { valid: res.valid, invalid: res.invalid, satisfaction: res.satisfaction, file: res.file });
      rec.check("BO-API-15", "breakdowns rendered in API order: categories LOST_PARCEL 2, DAMAGE 1; statuses CLOSED 2, OPEN 1",
        JSON.stringify(res.categories) === JSON.stringify([["LOST_PARCEL", "2"], ["DAMAGE", "1"]]) && JSON.stringify(res.statuses) === JSON.stringify([["CLOSED", "2"], ["OPEN", "1"]]),
        { categories: res.categories, statuses: res.statuses });
      rec.check("BO-API-16", "invalid records listed: 2 cards (INC-4 with 7 errors, empty id with 2 errors)",
        /Se encontraron 2 registros con errores/.test(res.invalid_status) &&
          JSON.stringify(res.invalid_records) === JSON.stringify([{ title: "Incidente: INC-4", errors: 7 }, { title: "Incidente:", errors: 2 }]),
        { status: res.invalid_status, records: res.invalid_records });

      // Export button -> GET /api/incidents/results/export (download denied, nothing written).
      const before = page.state.responses.length;
      await page.eval(`document.querySelector('#exportButton').click();true`);
      const exp = await waitFor(() => page.state.responses.slice(before).find((x) => x.path === "/api/incidents/results/export"), 10000);
      rec.check("BO-API-17", "export button requests /api/incidents/results/export -> 200 text/csv", exp?.status === 200 && exp.mimeType === "text/csv", exp);
      const csv = await page.eval(`fetch(EXPORT_URL).then(r=>r.text())`);
      rec.check("BO-API-18", "EXPORT_URL content after the UI analysis equals the expected metric,value CSV", csv === EXPECTED_EXPORT, { csv });
      const stillHere = await page.eval(`location.pathname`);
      rec.check("BO-API-19", "page stays on /backoffice/ after export (attachment download)", stillHere === "/backoffice/", { path: stillHere });
      const st = await linkStatus(page);
      rec.check("BO-API-20", "header link to the website resolves to 404 in mounted mode (API does not serve uis/website)", st === 404, { status: st }, "as-is-quirk");
      rec.check("BO-API-21", "no request left 127.0.0.1 except the Tailwind CDN; nothing blocked",
        page.state.blocked.length === 0 && page.state.requests.every((x) => x.host.startsWith("127.0.0.1") || x.host === CDN), { blocked: page.state.blocked });
      await page.close();
    }
  } catch (e) {
    rec.abort(e);
  } finally {
    cleanup = await browser.close();
    if (api) {
      killTree(api.proc);
      cleanup.apiStopped = await waitExit(api.proc, 8000);
    }
  }
  // /analyze keeps a temp copy of every upload (delete=False). Observed, then discarded with the dir.
  const leftovers = fs.existsSync(apiTemp) ? fs.readdirSync(apiTemp).filter((f) => f.endsWith(".csv")).length : -1;
  if (api) rec.check("BO-API-22", "/analyze left one temp .csv per upload (2) in the redirected TEMP dir", leftovers === 2, { leftovers }, "as-is-quirk");
  cleanup.apiTempRemoved = removeDir(apiTemp);
  cleanup.workRemoved = removeDir(work);
  rec.check("BO-CLEAN", "uvicorn stopped; Chrome profile, synthetic files and API temp dir removed",
    cleanup.profileRemoved && cleanup.apiTempRemoved && cleanup.workRemoved && (api ? cleanup.apiStopped : true), cleanup);
  return rec;
}
