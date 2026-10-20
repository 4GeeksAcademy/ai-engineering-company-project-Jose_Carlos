// U-A4 — reference run of the real dataset through the analyzer of the backoffice (Next.js).
//
//   node tests/ui/ua4_dataset_reference.mjs
//
// Flow: csv/incidents-trackflow.csv -> backoffice / (file input, signed in) -> POST /analyze ->
// rendered results -> export button -> GET /api/incidents/results/export. Every value is compared
// with the R4-B golden (tests/golden/analyzer_incidents_trackflow.r4b.json).
//
// Kept apart from run.mjs (U-A5 suites). Same guards as backoffice.mjs: only 127.0.0.1 is reachable;
// uvicorn (disposable TinyDB/SQLite) runs with TEMP/TMP/TMPDIR in a disposable directory, removed at
// the end with anything /analyze might have written (the upload contains the dataset's personal data);
// downloads are denied. Output: aggregates and counts only — no incident ids, emails or row values.

import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { PAGE_HELPERS, Recorder, killAll, killTree, launchChrome, makeTempDir, openPage, removeDir, waitExit, waitFor } from "./lib/harness.mjs";
import { TOKEN_KEY, createUser, signIn, startStack } from "./lib/backoffice-app.mjs";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const golden = JSON.parse(fs.readFileSync(path.join(repoRoot, "tests", "golden", "analyzer_incidents_trackflow.r4b.json"), "utf8"));
const G = golden.r4b_output;
const dataset = path.join(repoRoot, golden.provenance.dataset);
const policy = ({ url }) => url.hostname === "127.0.0.1";
const sha256 = (file) => crypto.createHash("sha256").update(fs.readFileSync(file)).digest("hex");
const expectedExport = ["metric,value", `valid_rows,${G.valid}`, `invalid_rows,${G.invalid}`,
  ...Object.entries(G.categories).map(([k, v]) => `category_${k},${v}`),
  ...Object.entries(G.statuses).map(([k, v]) => `status_${k},${v}`),
  `average_satisfaction,${G.media_satisfaccion.toFixed(2)}`].join("\r\n") + "\r\n";

for (const sig of ["SIGINT", "SIGTERM"]) process.on(sig, () => { killAll(); process.exit(130); });
process.on("exit", killAll);
setTimeout(() => { console.error("GLOBAL TIMEOUT"); killAll(); process.exit(3); }, 5 * 60 * 1000).unref();

const rec = new Recorder("ua4");
const apiTemp = makeTempDir("ua4-api-tmp");
const hashBefore = sha256(dataset);
let browser = null, stack = null, cleanup = {};
console.log("=== U-A4 real dataset through the backoffice analyzer ===");
try {
  rec.check("UA4-00", "dataset is the R4-B dataset (sha256 matches the golden)", hashBefore === golden.provenance.dataset_sha256, { sha256: hashBefore });

  stack = await startStack(repoRoot, apiTemp);
  const { api, app } = stack;
  const apiHost = new URL(api.origin).host;
  const { token } = await createUser(api.origin, "ua4-ui@trackflow.com", "ua4-ui-1234");

  browser = await launchChrome();
  const page = await openPage(browser, { policy });
  await browser.send("Browser.setDownloadBehavior", { behavior: "deny" }).catch(() => {});
  await signIn(page, app.origin, token);
  const nav = await page.goto(app.origin + "/", 120000);
  await waitFor(() => page.eval(`!!document.querySelector('#analysisForm')`), 60000);
  rec.check("UA4-01", "the analyzer (/) loads with a session and 0 uncaught exceptions", nav.loaded && page.state.exceptions.length === 0, { exceptions: page.state.exceptions.length });

  await page.setFile("#csvFile", dataset);
  await waitFor(() => page.eval(`!document.querySelector('#analyzeButton').disabled`), 3000);
  await page.eval(`document.querySelector('#analysisForm').requestSubmit();true`);
  const done = await waitFor(() => page.eval(`(()=>{${PAGE_HELPERS}const m=txt('#requestMessage');return txt('#analyzeButtonText')==='Analizar archivo'&&m?{message:m,error_style:q('#requestMessage').className.includes('text-red-800'),results_visible:vis('#resultsSection').visible,export_disabled:q('#exportButton').disabled}:null})()`), 20000);
  const post = page.state.responses.filter((x) => x.host === apiHost && x.path === "/analyze" && x.type !== "Preflight");
  rec.check("UA4-02", "POST /analyze (local API) -> 200 application/json", post.length === 1 && post[0].status === 200 && post[0].mimeType === "application/json", post);
  rec.check("UA4-03", "success message (invalid rows present), results visible, export enabled",
    done?.message === "Análisis completado. Se encontraron registros que requieren revisión." && !done.error_style && done.results_visible && !done.export_disabled, done);

  const ui = await page.eval(`(()=>{${PAGE_HELPERS}const rows=(id)=>qa(id+' > div').map(d=>[txt(d.querySelector('dt')),Number(txt(d.querySelector('dd')))]);
    const errs={};qa('#invalidRecordsList li').forEach(li=>{const t=txt(li);errs[t]=(errs[t]||0)+1;});return {
    valid:txt('#validCount'),invalid:txt('#invalidCount'),satisfaction:txt('#satisfactionAverage'),file:txt('#resultsFileName'),
    categories:rows('#categoriesList'),statuses:rows('#statusesList'),invalid_status:txt('#invalidRecordsStatus'),
    invalid_cards:qa('#invalidRecordsList article').length,error_counts:errs}})()`);
  rec.check("UA4-04", `metrics rendered = golden: valid ${G.valid}, invalid ${G.invalid}, satisfaction ${G.media_satisfaccion.toFixed(2)}`,
    ui.valid === String(G.valid) && ui.invalid === String(G.invalid) && ui.satisfaction === G.media_satisfaccion.toFixed(2) && ui.file === `Archivo: ${path.basename(dataset)}`,
    { valid: ui.valid, invalid: ui.invalid, satisfaction: ui.satisfaction });
  rec.check("UA4-05", "category and status breakdowns rendered = golden (values and order)",
    JSON.stringify(ui.categories) === JSON.stringify(Object.entries(G.categories)) && JSON.stringify(ui.statuses) === JSON.stringify(Object.entries(G.statuses)),
    { categories: ui.categories, statuses: ui.statuses });
  const sortObj = (o) => JSON.stringify(Object.fromEntries(Object.entries(o).sort()));
  rec.check("UA4-06", `invalid records rendered = golden: ${G.invalid_records_listed} cards, error message type counts`,
    ui.invalid_cards === G.invalid_records_listed && ui.invalid_status.includes(`Se encontraron ${G.invalid_records_listed} registros con errores`) && sortObj(ui.error_counts) === sortObj(G.error_message_type_counts),
    { cards: ui.invalid_cards, error_counts: ui.error_counts });

  const before = page.state.responses.length;
  await page.eval(`document.querySelector('#exportButton').click();true`);
  const exp = await waitFor(() => page.state.responses.slice(before).find((x) => x.path === "/api/incidents/results/export" && x.type !== "Preflight"), 10000);
  rec.check("UA4-07", "export button -> GET /api/incidents/results/export 200 text/csv (download denied)", exp?.status === 200 && exp.mimeType === "text/csv", exp);
  const csv = await page.eval(`fetch(${JSON.stringify(api.origin + "/api/incidents/results/export")},{headers:{Authorization:'Bearer '+localStorage.getItem(${JSON.stringify(TOKEN_KEY)})}}).then(r=>r.text())`);
  rec.check("UA4-08", "export CSV = rows derived from the golden", csv === expectedExport, { csv });
  rec.check("UA4-09", "no request left 127.0.0.1; nothing blocked",
    page.state.blocked.length === 0 && page.state.requests.every((x) => x.host.startsWith("127.0.0.1")), { blocked: page.state.blocked });
  await page.close();
} catch (e) {
  rec.abort(e);
} finally {
  if (browser) cleanup = await browser.close();
  if (stack) {
    killTree(stack.app.proc);
    killTree(stack.api.proc);
    cleanup.nextStopped = await waitExit(stack.app.proc, 8000);
    cleanup.apiStopped = await waitExit(stack.api.proc, 8000);
  }
}
const leftovers = fs.existsSync(apiTemp) ? fs.readdirSync(apiTemp).filter((f) => f.endsWith(".csv")).length : -1;
rec.check("UA4-10", "/analyze deleted its temp copy of the upload (0 left in the redirected TEMP dir)", leftovers === 0, { leftovers });
cleanup.apiTempRemoved = removeDir(apiTemp);
rec.check("UA4-11", "dataset unchanged (sha256 before = after)", sha256(dataset) === hashBefore);
rec.check("UA4-CLEAN", "uvicorn and next dev stopped; Chrome profile and API temp dir removed",
  cleanup.profileRemoved && cleanup.apiTempRemoved && cleanup.apiStopped && cleanup.nextStopped, cleanup);

const failed = rec.checks.filter((c) => !c.ok);
console.log(`=== U-A4: ${rec.checks.length} checks, ${rec.checks.length - failed.length} passed, ${failed.length} failed ===`);
process.exitCode = failed.length ? 1 : 0;
