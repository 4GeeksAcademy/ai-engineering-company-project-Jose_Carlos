// Medición Lighthouse repetible de los dos frontends en modo producción (hito 11).
//
//   node tests/perf/lighthouse.mjs <etiqueta>                p. ej. `before` o `after`
//   node tests/perf/lighthouse.mjs <etiqueta> backoffice-login   solo esas páginas (se añaden al resumen)
//
// Arranca todo lo necesario y lo para al terminar. Usa puertos y carpeta de build propios para
// poder medir aunque la app esté arrancada a mano en 3000/3001/8000:
//   * web pública: `serve` sobre uis/website/trackflow-web            -> http://localhost:4000
//   * API: uvicorn con TinyDB/SQLite desechables (nunca el Supabase del .env) -> http://localhost:8100
//   * backoffice: `npm run build` + `npm run start` con NEXT_DIST_DIR=.next-lighthouse -> http://localhost:4001
//   * Chrome headless con un perfil temporal, al que se conecta la CLI de Lighthouse.
//
// Cada página se mide 3 veces en móvil y 3 en escritorio y se toma la mediana por puntuación de
// Performance (Lighthouse recomienda varias ejecuciones porque Performance varía entre runs).
// Las vistas con sesión se miden con un token de una cuenta sintética en localStorage, como un usuario
// que vuelve (la vista se abre una vez antes); la caché HTTP se vacía antes de cada run, así que
// todas son cargas en frío de red.
//
// Salida: docs/lighthouse/<etiqueta>/summary.json y el informe HTML de la run mediana de cada caso.

import fs from "node:fs";
import path from "node:path";
import { spawn, execSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { findChrome, groupSpawn, killAll, killTree, makeTempDir, removeDir, track, waitFor } from "../ui/lib/harness.mjs";
import { TOKEN_KEY, createUser, startApi } from "../ui/lib/backoffice-app.mjs";

const LIGHTHOUSE = "lighthouse@13.5.0";
const SERVE = "serve@14.2.4";
const RUNS = 3;
const CHROME_PORT = 9333;
const WEBSITE = "http://localhost:4000";
const BACKOFFICE = "http://localhost:4001";
const API_PORT = 8100;
const API = `http://localhost:${API_PORT}`;

const PAGES = [
  { id: "website-home", url: `${WEBSITE}/` },
  { id: "website-application", url: `${WEBSITE}/application` },
  { id: "backoffice-login", url: `${BACKOFFICE}/login` },
  { id: "backoffice-analyzer", url: `${BACKOFFICE}/`, auth: true },
];
const FORM_FACTORS = ["mobile", "desktop"];

const [label, ...only] = process.argv.slice(2);
if (!label) {
  console.error("Uso: node tests/perf/lighthouse.mjs <etiqueta> [id de página…]");
  process.exit(2);
}
const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const outDir = path.join(repoRoot, "docs", "lighthouse", label);
fs.mkdirSync(outDir, { recursive: true });

const isWin = process.platform === "win32";
const npx = (args, opts = {}) =>
  track(spawn(isWin ? "npx.cmd" : "npx", args, { shell: isWin, stdio: ["ignore", "pipe", "pipe"], ...groupSpawn, ...opts }));

for (const sig of ["SIGINT", "SIGTERM"]) process.on(sig, () => { killAll(); process.exit(130); });
process.on("exit", killAll);

async function isUp(url) {
  try {
    return (await fetch(url)).status < 500;
  } catch {
    return false;
  }
}

async function cdp(wsUrl) {
  const ws = new WebSocket(wsUrl);
  let seq = 0;
  const pending = new Map();
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.id && pending.has(msg.id)) {
      const { resolve, reject } = pending.get(msg.id);
      pending.delete(msg.id);
      msg.error ? reject(new Error(JSON.stringify(msg.error))) : resolve(msg.result);
    }
  };
  const send = (method, params = {}, sessionId) => {
    const id = ++seq;
    ws.send(JSON.stringify({ id, method, params, sessionId }));
    return new Promise((resolve, reject) => pending.set(id, { resolve, reject }));
  };
  return { send, close: () => ws.close() };
}

/** Vacía la caché HTTP y, si hay token, deja la sesión abierta en el origen del backoffice. */
async function prepareBrowser(token) {
  const { webSocketDebuggerUrl } = await (await fetch(`http://127.0.0.1:${CHROME_PORT}/json/version`)).json();
  const browser = await cdp(webSocketDebuggerUrl);
  const { targetId } = await browser.send("Target.createTarget", { url: "about:blank" });
  const { sessionId } = await browser.send("Target.attachToTarget", { targetId, flatten: true });
  await browser.send("Network.enable", {}, sessionId);
  if (token !== undefined) {
    await browser.send("Page.enable", {}, sessionId);
    await browser.send("Page.navigate", { url: `${BACKOFFICE}/login` }, sessionId);
    await waitFor(async () => {
      const r = await browser.send("Runtime.evaluate", { expression: "document.readyState", returnByValue: true }, sessionId);
      return r.result.value === "complete";
    }, 30000);
    const expression = token
      ? `localStorage.setItem(${JSON.stringify(TOKEN_KEY)}, ${JSON.stringify(token)})`
      : "localStorage.clear()";
    await browser.send("Runtime.evaluate", { expression }, sessionId);
    if (token) {
      // Usuario que vuelve: abre la vista una vez con la sesión (como quien ya estaba trabajando)
      // y se mide la siguiente carga. Solo se conserva localStorage; la caché HTTP se vacía abajo.
      await browser.send("Page.navigate", { url: `${BACKOFFICE}/` }, sessionId);
      await waitFor(async () => {
        const r = await browser.send("Runtime.evaluate", { expression: "!!document.querySelector('#page-title')", returnByValue: true }, sessionId);
        return r.result.value === true;
      }, 30000);
    }
  }
  // Después de abrir /login (que deja sus ficheros en caché): la run tiene que ser en frío.
  await browser.send("Network.clearBrowserCache", {}, sessionId);
  await browser.send("Target.closeTarget", { targetId });
  browser.close();
}

function runLighthouse(page, formFactor, run) {
  const base = path.join(tmpDir, `${page.id}-${formFactor}-${run}`);
  const args = [
    "-y", LIGHTHOUSE, page.url,
    `--port=${CHROME_PORT}`,
    "--output=json", "--output=html", `--output-path=${base}`,
    "--only-categories=performance,accessibility,best-practices,seo",
    "--quiet",
  ];
  if (formFactor === "desktop") args.push("--preset=desktop");
  // Con sesión no se puede dejar que Lighthouse borre el almacenamiento (se perdería el token).
  if (page.auth) args.push("--disable-storage-reset");
  execSync(`${isWin ? "npx.cmd" : "npx"} ${args.map((a) => `"${a}"`).join(" ")}`, { stdio: "ignore", timeout: 240000 });
  return { json: JSON.parse(fs.readFileSync(`${base}.report.json`, "utf8")), html: `${base}.report.html` };
}

const METRICS = {
  FCP: "first-contentful-paint",
  LCP: "largest-contentful-paint",
  TBT: "total-blocking-time",
  CLS: "cumulative-layout-shift",
  SI: "speed-index",
};

function summarize(lhr) {
  const scores = Object.fromEntries(Object.entries(lhr.categories).map(([k, c]) => [k, Math.round(c.score * 100)]));
  const metrics = Object.fromEntries(Object.entries(METRICS).map(([k, id]) => [k, { value: lhr.audits[id].numericValue, display: lhr.audits[id].displayValue }]));
  // Auditorías que no pasan (o tienen ahorro estimado) en cualquier categoría.
  const auditCategory = {};
  for (const [cat, c] of Object.entries(lhr.categories)) for (const ref of c.auditRefs) auditCategory[ref.id] ??= cat;
  const issues = Object.values(lhr.audits)
    .filter((a) => auditCategory[a.id] && a.score !== null && a.score < 0.9 && !["manual", "notApplicable", "informative"].includes(a.scoreDisplayMode))
    .filter((a) => !Object.values(METRICS).includes(a.id))
    .map((a) => ({ id: a.id, category: auditCategory[a.id], title: a.title, score: a.score, display: a.displayValue ?? null, savings: a.metricSavings ?? null }));
  const lcpItems = lhr.audits["lcp-breakdown-insight"]?.details?.items ?? [];
  const lcpElement = lcpItems.find((i) => i.type === "node")?.snippet ?? null;
  const lcpPhases = lcpItems.find((i) => i.type === "table")?.items
    ?.map((i) => ({ phase: i.label ?? i.subpart, ms: Math.round(i.duration) })) ?? null;
  const requests = lhr.audits["network-requests"]?.details?.items ?? [];
  const transfer = Math.round(requests.reduce((s, r) => s + (r.transferSize || 0), 0) / 1024);
  return { scores, metrics, lcpElement, lcpPhases, requests: requests.length, transferKiB: transfer, issues };
}

const tmpDir = makeTempDir("lighthouse");
const apiTemp = makeTempDir("lighthouse-api");
let chrome = null;
let profileDir = null;
const summaryFile = path.join(outDir, "summary.json");
const previous = fs.existsSync(summaryFile) ? JSON.parse(fs.readFileSync(summaryFile, "utf8")) : { pages: {} };
const results = { label, date: new Date().toISOString(), lighthouse: LIGHTHOUSE, runs: RUNS, pages: only.length ? previous.pages : {} };

try {
  for (const url of [WEBSITE, API, BACKOFFICE]) {
    if (await isUp(url)) throw new Error(`${url} ya está en uso.`);
  }

  console.log("· web pública (serve)");
  npx(["-y", SERVE, "trackflow-web", "-l", "4000"], { cwd: path.join(repoRoot, "uis", "website") });
  if (!(await waitFor(() => isUp(`${WEBSITE}/`), 120000, 500))) throw new Error("serve no arrancó");

  console.log("· API (uvicorn, base de datos desechable)");
  await startApi(repoRoot, apiTemp, { port: API_PORT, corsOrigins: [BACKOFFICE] });
  const { token } = await createUser(`http://127.0.0.1:${API_PORT}`, "lighthouse@trackflow.com", "lighthouse-1234");

  console.log("· backoffice: npm run build");
  const backofficeDir = path.join(repoRoot, "uis", "backoffice");
  const env = {
    ...process.env,
    NEXT_TELEMETRY_DISABLED: "1",
    NEXT_DIST_DIR: ".next-lighthouse",
    NEXT_PUBLIC_AUTH_API_URL: API,
    NEXT_PUBLIC_WEBSITE_URL: `${WEBSITE}/`,
  };
  // `next build` con otro distDir reescribe tsconfig.json y next-env.d.ts apuntando a esa carpeta:
  // se guardan antes y se dejan como estaban.
  const touched = ["tsconfig.json", "next-env.d.ts"].map((f) => path.join(backofficeDir, f));
  const saved = touched.map((f) => (fs.existsSync(f) ? fs.readFileSync(f) : null));
  try {
    execSync("npm run build", { cwd: backofficeDir, stdio: "ignore", env });
  } finally {
    touched.forEach((f, i) => (saved[i] === null ? fs.rmSync(f, { force: true }) : fs.writeFileSync(f, saved[i])));
  }
  console.log("· backoffice: npm run start");
  track(spawn(isWin ? "npm.cmd" : "npm", ["run", "start", "--", "--port", "4001"], { cwd: backofficeDir, shell: isWin, stdio: "ignore", env, ...groupSpawn }));
  if (!(await waitFor(() => isUp(`${BACKOFFICE}/login`), 60000, 500))) throw new Error("next start no arrancó");

  profileDir = makeTempDir("lighthouse-chrome");
  chrome = track(spawn(findChrome(), [
    "--headless=new", `--remote-debugging-port=${CHROME_PORT}`, `--user-data-dir=${profileDir}`,
    "--no-first-run", "--no-default-browser-check", "--disable-extensions", "--disable-sync",
    "--disable-background-networking", "--disable-component-update", "about:blank",
  ], { stdio: "ignore", ...groupSpawn }));
  if (!(await waitFor(() => isUp(`http://127.0.0.1:${CHROME_PORT}/json/version`), 15000))) throw new Error("Chrome no arrancó");

  for (const page of PAGES.filter((p) => !only.length || only.includes(p.id))) {
    for (const formFactor of FORM_FACTORS) {
      const runs = [];
      for (let i = 1; i <= RUNS; i++) {
        await prepareBrowser(page.auth ? token : page.url.startsWith(BACKOFFICE) ? "" : undefined);
        const r = runLighthouse(page, formFactor, i);
        runs.push({ ...summarize(r.json), html: r.html });
        console.log(`  ${page.id} ${formFactor} #${i}: ${JSON.stringify(runs.at(-1).scores)} LCP ${runs.at(-1).metrics.LCP.display}`);
      }
      runs.sort((a, b) => a.scores.performance - b.scores.performance);
      const median = runs[Math.floor(runs.length / 2)];
      fs.copyFileSync(median.html, path.join(outDir, `${page.id}-${formFactor}.html`));
      delete median.html;
      results.pages[`${page.id}-${formFactor}`] = {
        url: page.url,
        formFactor,
        median,
        performanceRange: [runs[0].scores.performance, runs.at(-1).scores.performance],
        lcpRangeMs: [Math.min(...runs.map((r) => r.metrics.LCP.value)), Math.max(...runs.map((r) => r.metrics.LCP.value))].map(Math.round),
      };
    }
  }

  fs.writeFileSync(summaryFile, JSON.stringify(results, null, 2) + "\n");
  console.log(`\nResumen en ${path.relative(repoRoot, outDir)}`);
  console.log("caso | Perf | A11y | BP | SEO | FCP | LCP | TBT | CLS");
  for (const [id, p] of Object.entries(results.pages)) {
    const s = p.median.scores;
    const m = p.median.metrics;
    console.log(`${id} | ${s.performance} | ${s.accessibility} | ${s["best-practices"]} | ${s.seo} | ${m.FCP.display} | ${m.LCP.display} | ${m.TBT.display} | ${m.CLS.display}`);
  }
} finally {
  if (chrome) killTree(chrome);
  killAll();
  removeDir(tmpDir);
  removeDir(apiTemp);
  removeDir(profileDir);
}
