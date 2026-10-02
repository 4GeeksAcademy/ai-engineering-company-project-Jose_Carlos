// U-A4 — reference run of the real dataset through the backoffice mounted in FastAPI.
//
//   node tests/ui/ua4_dataset_reference.mjs
//
// Flow: csv/incidents-trackflow.csv -> backoffice /backoffice/ (file input) -> POST /analyze ->
// rendered results -> export button -> GET /api/incidents/results/export. Every value is compared
// with the R4-B golden (tests/golden/analyzer_incidents_trackflow.r4b.json).
//
// Kept apart from run.mjs (U-A5 suites). Same guards as backoffice.mjs: only 127.0.0.1 and the
// Tailwind CDN (GET) are reachable; uvicorn runs with TEMP/TMP/TMPDIR in a disposable directory,
// because /analyze leaves a copy of the upload there (it contains the dataset's personal data and is
// deleted with the directory); downloads are denied. Output: aggregates and counts only — no
// incident ids, emails or row values.

import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import {
  PAGE_HELPERS, Recorder, freePort, groupSpawn, killAll, killTree, launchChrome, makeTempDir, openPage,
  removeDir, track, waitExit, waitFor,
} from "./lib/harness.mjs";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const golden = JSON.parse(fs.readFileSync(path.join(repoRoot, "tests", "golden", "analyzer_incidents_trackflow.r4b.json"), "utf8"));
const G = golden.r4b_output;
const dataset = path.join(repoRoot, golden.provenance.dataset);
const CDN = "cdn.tailwindcss.com";
const policy = ({ method, url }) => url.hostname === "127.0.0.1" || (url.hostname === CDN && (method === "GET" || method === "HEAD"));
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
let browser = null, api = null, cleanup = {};
console.log("=== U-A4 real dataset through the mounted backoffice ===");
try {
  rec.check("UA4-00", "dataset is the R4-B dataset (sha256 matches the golden)", hashBefore === golden.provenance.dataset_sha256, { sha256: hashBefore });

  const python = process.env.PYTHON || [path.join(repoRoot, ".venv", "Scripts", "python.exe"), path.join(repoRoot, ".venv", "bin", "python")].find((p) => fs.existsSync(p));
  if (!python) throw new Error("Project virtualenv not found: run `uv sync --frozen` first (or set PYTHON).");
  const port = await freePort();
  const proc = track(spawn(python, ["-m", "uvicorn", "services.api.main:app", "--host", "127.0.0.1", "--port", String(port)], {
    cwd: repoRoot, env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1", TEMP: apiTemp, TMP: apiTemp, TMPDIR: apiTemp },
    stdio: ["ignore", "ignore", "ignore"], ...groupSpawn,
  }));
  api = { proc, origin: `http://127.0.0.1:${port}` };
  if (!(await waitFor(async () => (await fetch(api.origin + "/")).status === 200, 30000, 250))) throw new Error("uvicorn did not become ready");

  browser = await launchChrome({ allowedHosts: [CDN] });
  const page = await openPage(browser, { policy });
  await browser.send("Browser.setDownloadBehavior", { behavior: "deny" }).catch(() => {});
  const nav = await page.goto(api.origin + "/backoffice/");
  await waitFor(() => page.eval(`(()=>{${PAGE_HELPERS}return tailwindReady()})()`), 20000);
  rec.check("UA4-01", "/backoffice/ served by the API loads with 0 uncaught exceptions", nav.loaded && page.state.exceptions.length === 0, { exceptions: page.state.exceptions.length });

  await page.setFile("#csvFile", dataset);
  await waitFor(() => page.eval(`!document.querySelector('#analyzeButton').disabled`), 3000);
  await page.eval(`document.querySelector('#analysisForm').requestSubmit();true`);
  const done = await waitFor(() => page.eval(`(()=>{${PAGE_HELPERS}const m=txt('#requestMessage');return txt('#analyzeButtonText')==='Analizar archivo'&&m?{message:m,error_style:q('#requestMessage').className.includes('text-red-800'),results_visible:vis('#resultsSection').visible,export_disabled:q('#exportButton').disabled}:null})()`), 20000);
  const post = page.state.responses.filter((x) => x.path === "/analyze");
  rec.check("UA4-02", "POST /analyze (same origin) -> 200 application/json", post.length === 1 && post[0].status === 200 && post[0].mimeType === "application/json", post);
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
  const exp = await waitFor(() => page.state.responses.slice(before).find((x) => x.path === "/api/incidents/results/export"), 10000);
  rec.check("UA4-07", "export button -> GET /api/incidents/results/export 200 text/csv (download denied)", exp?.status === 200 && exp.mimeType === "text/csv", exp);
  const csv = await page.eval(`fetch(EXPORT_URL).then(r=>r.text())`);
  rec.check("UA4-08", "export CSV = rows derived from the golden", csv === expectedExport, { csv });
  rec.check("UA4-09", "no request left 127.0.0.1 except the Tailwind CDN; nothing blocked",
    page.state.blocked.length === 0 && page.state.requests.every((x) => x.host.startsWith("127.0.0.1") || x.host === CDN), { blocked: page.state.blocked });
  await page.close();
} catch (e) {
  rec.abort(e);
} finally {
  if (browser) cleanup = await browser.close();
  if (api) { killTree(api.proc); cleanup.apiStopped = await waitExit(api.proc, 8000); }
}
const leftovers = fs.existsSync(apiTemp) ? fs.readdirSync(apiTemp).filter((f) => f.endsWith(".csv")).length : -1;
rec.check("UA4-10", "/analyze left its temp copy (1) in the redirected TEMP dir — AS-IS, removed now", leftovers === 1, { leftovers }, "as-is-quirk");
cleanup.apiTempRemoved = removeDir(apiTemp);
rec.check("UA4-11", "dataset unchanged (sha256 before = after)", sha256(dataset) === hashBefore);
rec.check("UA4-CLEAN", "uvicorn stopped; Chrome profile and API temp dir (with the upload copy) removed",
  cleanup.profileRemoved && cleanup.apiTempRemoved && cleanup.apiStopped, cleanup);

const failed = rec.checks.filter((c) => !c.ok);
console.log(`=== U-A4: ${rec.checks.length} checks, ${rec.checks.length - failed.length} passed, ${failed.length} failed ===`);
process.exitCode = failed.length ? 1 : 0;
