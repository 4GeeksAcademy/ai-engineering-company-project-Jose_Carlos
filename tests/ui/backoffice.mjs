// Backoffice baseline (BP-3): analizador de incidentes CSV en el backoffice Next.js (uis/backoffice),
// derivado de R4-C3 (render), R4-B (camino de error) y la referencia U-A4 (análisis + export).
//
// Arranca la API (uvicorn, TinyDB/SQLite desechables) y `next dev` del backoffice apuntando a ella,
// abre una sesión con una cuenta sintética y recorre la página `/`: guard de sesión, render, envío
// sin archivo, API inaccesible, CSV no UTF-8, análisis de un CSV sintético y export.
//
// Solo se sube contenido sintético y solo a 127.0.0.1. uvicorn corre con TEMP/TMP/TMPDIR en un
// directorio desechable y sin escribir bytecode. Las descargas se deniegan en el navegador.

import fs from "node:fs";
import path from "node:path";
import { PAGE_HELPERS, Recorder, killTree, launchChrome, makeTempDir, openPage, removeDir, waitExit, waitFor } from "./lib/harness.mjs";
import { TOKEN_KEY, createUser, signIn, startStack } from "./lib/backoffice-app.mjs";

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
const EMAIL = "analizador-ui@trackflow.com";
const PASSWORD = "analizador-ui-1234";
const WEBSITE_URL = "http://localhost:3000/";

const RENDER_DOM = `(()=>{${PAGE_HELPERS}const fi=q('input[type=file]');return {
  title:document.title, header:vis('header').visible, badge:{text:txt('header span'),visible:vis('header span').visible},
  nav:qa('header nav a').map(a=>({text:txt(a),href:a.getAttribute('href'),current:a.getAttribute('aria-current')})),
  h1:{text:txt('#page-title'),visible:vis('#page-title').visible}, form:vis('#analysisForm').visible,
  file_input:{present:!!fi,accept:fi?.getAttribute('accept'),name:fi?.getAttribute('name'),label_visible:fi?.labels?.[0]?vis(fi.labels[0]).visible:false},
  analyze:{text:txt('#analyzeButton'),disabled:q('#analyzeButton').disabled,visible:vis('#analyzeButton').visible},
  export_:{text:txt('#exportButton'),disabled:q('#exportButton').disabled,visible:vis('#exportButton').visible},
  results:{hidden_class:q('#resultsSection').classList.contains('hidden'),visible:vis('#resultsSection').visible},
  message:{hidden_class:q('#requestMessage').classList.contains('hidden'),visible:vis('#requestMessage').visible},
  metrics_visible:['#validCount','#invalidCount','#satisfactionAverage'].some(s=>vis(s).visible),
  selected_file_visible:vis('#selectedFile').visible, spinner_visible:vis('#loadingSpinner').visible,
  hidden_audit:hiddenAudit(), overflow:overflowX(), website_link:q('header a')?.getAttribute('href')}})()`;

const AFTER_SUBMIT = `(()=>{${PAGE_HELPERS}return {message:txt('#requestMessage'),message_visible:vis('#requestMessage').visible,
  error_style:q('#requestMessage').className.includes('text-red-800'),button_text:txt('#analyzeButtonText'),
  analyze_disabled:q('#analyzeButton').disabled,spinner_hidden:q('#loadingSpinner').classList.contains('hidden'),
  results_visible:vis('#resultsSection').visible,export_disabled:q('#exportButton').disabled}})()`;

const waitIdle = (page) => waitFor(async () => {
  const s = await page.eval(AFTER_SUBMIT);
  return s.button_text === "Analizar archivo" && s.message ? s : null;
}, 20000);

const NAV_EXPECTED = [
  ["Incidentes", "/"], ["Gestor de incidencias", "/incidents"], ["Registrar incidencia", "/incidents/new"],
  ["Proveedores", "/suppliers"], ["Inventario", "/inventory/products"], ["Talent Pipeline", "/talent"],
];

export async function run({ repoRoot }) {
  const rec = new Recorder("backoffice");
  const work = makeTempDir("backoffice");
  const apiTemp = makeTempDir("api-tmp");
  const csvFile = path.join(work, "synthetic-incidents.csv");
  const badFile = path.join(work, "synthetic-latin1.csv");
  fs.writeFileSync(csvFile, SAMPLE_CSV, "utf8");
  fs.writeFileSync(badFile, Buffer.from("incident_id\nñ\n", "latin1"));
  const browser = await launchChrome();
  let stack = null;
  let cleanup = {};
  // El guard puede "desconectar" la API para comprobar el error de red.
  let apiReachable = true;

  try {
    stack = await startStack(repoRoot, apiTemp, { websiteUrl: WEBSITE_URL });
    const { api, app } = stack;
    const apiHost = new URL(api.origin).host;
    const policy = ({ url }) => url.hostname === "127.0.0.1" && (apiReachable || url.host !== apiHost);
    const { token } = await createUser(api.origin, EMAIL, PASSWORD);
    const page = await openPage(browser, { policy });
    await page.send("Browser.setDownloadBehavior", { behavior: "deny" }).catch(() => {});
    await browser.send("Browser.setDownloadBehavior", { behavior: "deny" }).catch(() => {});

    // ---------------------------------------------------------- guard de sesión
    await page.goto(app.origin + "/", 120000);
    const landed = await waitFor(() => page.eval(`location.pathname==='/login' && location.search`), 60000);
    rec.check("BO-AUTH", "without a session / redirects to /login?next=/", landed && new URLSearchParams(landed).get("next") === "/", { landed });

    const old = await page.goto(app.origin + "/index.html", 60000);
    const oldPath = await waitFor(() => page.eval(`location.pathname==='/login' && new URLSearchParams(location.search).get('next')`), 30000);
    rec.check("BO-ROUTE", "the old /index.html address redirects to the analyzer (/)", old.loaded && oldPath === "/", { next: oldPath });

    // ---------------------------------------------------------- render (sesión abierta)
    await signIn(page, app.origin, token);
    const nav = await page.goto(app.origin + "/", 120000);
    rec.check("BO-00", "page loads with a session (load event, no navigation error)", nav.loaded && !nav.navigationError, nav);
    await waitFor(() => page.eval(`!!document.querySelector('#analysisForm')`), 60000);
    const d = await page.eval(RENDER_DOM);
    rec.check("BO-01", "page loads with 0 uncaught exceptions", page.state.exceptions.length === 0, { exceptions: page.state.exceptions });
    rec.check("BO-02", "title, header with 'Backoffice' badge, h1 'Analizador de incidentes CSV' visible",
      d.title === "Analizador de incidentes | TrackFlow" && d.header && d.badge.visible && /backoffice/i.test(d.badge.text) && d.h1.visible && d.h1.text === "Analizador de incidentes CSV",
      { title: d.title, badge: d.badge, h1: d.h1 });
    rec.check("BO-NAV", "header nav: the 5 backoffice sections plus a 'Talent Pipeline' tab (/talent); 'Incidentes' is the current page",
      JSON.stringify(d.nav.map((n) => [n.text, n.href])) === JSON.stringify(NAV_EXPECTED) && d.nav[0].current === "page" && d.nav.slice(1).every((n) => !n.current),
      d.nav);
    rec.check("BO-03", "form visible; file input accepts .csv, field name 'file', visible drop-zone label",
      d.form && d.file_input.present && d.file_input.accept === ".csv,text/csv" && d.file_input.name === "file" && d.file_input.label_visible, d.file_input);
    rec.check("BO-04", "'Analizar archivo' and 'Descargar resultados CSV' visible and disabled before any file",
      d.analyze.visible && d.analyze.disabled && d.analyze.text === "Analizar archivo" && d.export_.visible && d.export_.disabled && d.export_.text === "Descargar resultados CSV",
      { analyze: d.analyze, export: d.export_ });
    rec.check("BO-05", "hidden before analysis: results section, request message, metrics, selected file, spinner",
      d.results.hidden_class && !d.results.visible && d.message.hidden_class && !d.message.visible && !d.metrics_visible && !d.selected_file_visible && !d.spinner_visible,
      { results: d.results, message: d.message });
    rec.check("BO-06", "every .hidden element computes to display:none", d.hidden_audit.shown_without_responsive_override.length === 0, d.hidden_audit);
    rec.check("BO-07", "no horizontal overflow at 1280px", d.overflow === 0, { overflow_px: d.overflow });
    rec.check("BO-08", "header logo links to the public website (NEXT_PUBLIC_WEBSITE_URL)", d.website_link === WEBSITE_URL, { href: d.website_link });

    const reqsBefore = page.state.requests.filter((r) => r.path === "/analyze").length;
    await page.eval(`document.querySelector('#analysisForm').requestSubmit();true`);
    const nf = await waitFor(async () => { const s = await page.eval(AFTER_SUBMIT); return s.message ? s : null; }, 5000);
    rec.check("BO-09", "submit without file shows the error message on screen and sends no request",
      nf?.message === "Selecciona un archivo CSV antes de iniciar el análisis." && nf.message_visible && nf.error_style &&
        page.state.requests.filter((r) => r.path === "/analyze").length === reqsBefore, nf);

    const selectFile = async (id, file) => {
      await page.setFile("#csvFile", file);
      const s = await waitFor(() => page.eval(`(()=>{${PAGE_HELPERS}return vis('#selectedFile').visible&&txt('#fileName')===${JSON.stringify(path.basename(file))}?{name:txt('#fileName'),size:txt('#fileSize'),analyze_disabled:q('#analyzeButton').disabled,message_hidden:q('#requestMessage').classList.contains('hidden')}:null})()`), 5000);
      rec.check(id, `selecting ${path.basename(file)} shows its name/size, enables 'Analizar archivo' and clears the message`,
        s?.name === path.basename(file) && !!s.size && !s.analyze_disabled && s.message_hidden, s);
    };

    // ---------------------------------------------------------- API inaccesible (R4-B)
    await selectFile("BO-10", csvFile);
    apiReachable = false;
    await page.eval(`document.querySelector('#analysisForm').requestSubmit();true`);
    const down = await waitIdle(page);
    apiReachable = true;
    const blocked = page.state.blocked.filter((b) => b.host === apiHost && b.path === "/analyze");
    rec.check("BO-11", "API unreachable: POST /analyze fails and a readable network error is shown",
      blocked.length >= 1 && down?.message === "No se pudo completar el análisis. No se pudo conectar con el servidor. Comprueba tu conexión e inténtalo de nuevo." &&
        down.error_style && !down.results_visible && down.export_disabled, { blocked: blocked.length, after: down });
    rec.check("BO-12", "after the API error: button restored, spinner hidden, results hidden, export disabled",
      down?.button_text === "Analizar archivo" && !down.analyze_disabled && down.spinner_hidden && !down.results_visible && down.export_disabled, down);

    // ---------------------------------------------------------- CSV no UTF-8 -> 400
    await selectFile("BO-13", badFile);
    await page.eval(`document.querySelector('#analysisForm').requestSubmit();true`);
    const bad = await waitIdle(page);
    rec.check("BO-14", "a non-UTF-8 file: API 400 shown as a readable message; results stay hidden, export disabled",
      bad?.message === "No se pudo completar el análisis. El archivo no es un CSV válido en UTF-8. Revisa el archivo y vuelve a subirlo." &&
        bad.error_style && !bad.results_visible && bad.export_disabled, bad);

    // ---------------------------------------------------------- análisis correcto
    await selectFile("BO-15", csvFile);
    await page.eval(`document.querySelector('#analysisForm').requestSubmit();true`);
    const ok = await waitIdle(page);
    const analyzeResp = page.state.responses.filter((x) => x.host === apiHost && x.path === "/analyze" && x.type !== "Preflight");
    rec.check("BO-16", "analysis POSTs to the API /analyze: 400 for the bad file, then 200 JSON",
      analyzeResp.length === 2 && analyzeResp[0].status === 400 && analyzeResp[1].status === 200 && analyzeResp[1].mimeType === "application/json", analyzeResp);
    rec.check("BO-17", "success message shown (invalid rows present), results visible, export enabled",
      ok?.message === "Análisis completado. Se encontraron registros que requieren revisión." && ok.message_visible && !ok.error_style && ok.results_visible && !ok.export_disabled, ok);
    const res = await page.eval(`(()=>{${PAGE_HELPERS}const rows=(id)=>qa(id+' > div').map(d=>[txt(d.querySelector('dt')),txt(d.querySelector('dd'))]);return {
      valid:txt('#validCount'),invalid:txt('#invalidCount'),satisfaction:txt('#satisfactionAverage'),file:txt('#resultsFileName'),
      categories:rows('#categoriesList'),statuses:rows('#statusesList'),invalid_status:txt('#invalidRecordsStatus'),
      invalid_records:qa('#invalidRecordsList article').map(a=>({title:txt(a.querySelector('h4')),errors:a.querySelectorAll('li').length}))}})()`);
    rec.check("BO-18", "metrics rendered: valid 3, invalid 2, satisfaction 4.50, file name",
      res.valid === "3" && res.invalid === "2" && res.satisfaction === "4.50" && res.file === "Archivo: synthetic-incidents.csv", res);
    rec.check("BO-19", "breakdowns rendered in API order: categories LOST_PARCEL 2, DAMAGE 1; statuses CLOSED 2, OPEN 1",
      JSON.stringify(res.categories) === JSON.stringify([["LOST_PARCEL", "2"], ["DAMAGE", "1"]]) && JSON.stringify(res.statuses) === JSON.stringify([["CLOSED", "2"], ["OPEN", "1"]]),
      { categories: res.categories, statuses: res.statuses });
    rec.check("BO-20", "invalid records listed: 2 cards (INC-4 with 7 errors, empty id with 2 errors)",
      /Se encontraron 2 registros con errores/.test(res.invalid_status) &&
        JSON.stringify(res.invalid_records) === JSON.stringify([{ title: "Incidente: INC-4", errors: 7 }, { title: "Incidente:", errors: 2 }]),
      { status: res.invalid_status, records: res.invalid_records });

    // ---------------------------------------------------------- export
    const before = page.state.responses.length;
    await page.eval(`document.querySelector('#exportButton').click();true`);
    const exp = await waitFor(() => page.state.responses.slice(before).find((x) => x.path === "/api/incidents/results/export" && x.type !== "Preflight"), 10000);
    rec.check("BO-21", "export button requests /api/incidents/results/export -> 200 text/csv", exp?.status === 200 && exp.mimeType === "text/csv", exp);
    const csv = await page.eval(`fetch(${JSON.stringify(api.origin + "/api/incidents/results/export")},{headers:{Authorization:'Bearer '+localStorage.getItem(${JSON.stringify(TOKEN_KEY)})}}).then(r=>r.text())`);
    rec.check("BO-22", "export content after the UI analysis equals the expected metric,value CSV", csv === EXPECTED_EXPORT, { csv });
    const stillHere = await page.eval(`location.pathname`);
    rec.check("BO-23", "page stays on / after export (attachment download)", stillHere === "/", { path: stillHere });
    rec.check("BO-NET", "no request left 127.0.0.1", page.state.requests.every((x) => x.host.startsWith("127.0.0.1")), { hosts: [...new Set(page.state.requests.map((x) => x.host))] });
    rec.check("BO-ERR", "no uncaught exceptions while using the analyzer", page.state.exceptions.length === 0, page.state.exceptions);
    await page.close();
  } catch (e) {
    rec.abort(e);
  } finally {
    cleanup = await browser.close();
    if (stack) {
      killTree(stack.app.proc);
      killTree(stack.api.proc);
      cleanup.nextStopped = await waitExit(stack.app.proc, 8000);
      cleanup.apiStopped = await waitExit(stack.api.proc, 8000);
    }
  }
  // /analyze borra su copia temporal (os.unlink en un finally): no debe quedar ninguna.
  const leftovers = fs.existsSync(apiTemp) ? fs.readdirSync(apiTemp).filter((f) => f.endsWith(".csv")).length : -1;
  if (stack) rec.check("BO-TEMP", "/analyze left no temp .csv copies in the redirected TEMP dir", leftovers === 0, { leftovers });
  cleanup.apiTempRemoved = removeDir(apiTemp);
  cleanup.workRemoved = removeDir(work);
  rec.check("BO-CLEAN", "uvicorn and next dev stopped; Chrome profile, synthetic files and API temp dir removed",
    cleanup.profileRemoved && cleanup.apiTempRemoved && cleanup.workRemoved && (stack ? cleanup.apiStopped && cleanup.nextStopped : true), cleanup);
  return rec;
}
