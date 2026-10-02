// Shared infrastructure for the TrackFlow UI baseline (U-A5).
//
// Zero npm dependencies: Node >= 22 (built-in fetch/WebSocket) drives an installed Chrome/Chromium
// through the DevTools protocol, the same technique used by the R4 audit harnesses.
//
// Every page opened through openPage() runs behind a CDP Fetch interceptor: each request is passed to
// a policy function and either continued or failed BEFORE it leaves the machine. DNS is additionally
// disabled for every host that is not explicitly allowlisted (--host-resolver-rules).

import http from "node:http";
import net from "node:net";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawn, execFileSync } from "node:child_process";

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export async function waitFor(fn, timeout = 20000, step = 150) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeout) {
    try {
      const v = await fn();
      if (v) return v;
    } catch {}
    await sleep(step);
  }
  return null;
}

// ------------------------------------------------------------------ results

export class Recorder {
  constructor(suite) {
    this.suite = suite;
    this.checks = [];
  }

  // kind "baseline": known-good behavior that must survive B/C.
  // kind "as-is-quirk": current behavior tied to an open finding; a planned unit is expected to change it.
  check(id, description, ok, detail = undefined, kind = "baseline") {
    const entry = { suite: this.suite, id, description, ok: !!ok, kind };
    if (detail !== undefined) entry.detail = detail;
    this.checks.push(entry);
    const tag = ok ? "PASS" : "FAIL";
    const quirk = kind === "as-is-quirk" ? " [as-is-quirk]" : "";
    const extra = !ok && detail !== undefined ? `  -> ${JSON.stringify(detail).slice(0, 400)}` : "";
    console.log(`  ${tag}  ${id}${quirk}  ${description}${extra}`);
    return !!ok;
  }

  // An aborted suite still reports a failing check so the run is never silently green.
  abort(error) {
    this.check(`${this.suite.toUpperCase()}-ABORT`, "suite completed without harness error", false, String(error?.message || error).slice(0, 300));
  }
}

// ------------------------------------------------------------------ processes

const children = new Set();

export function track(child) {
  children.add(child);
  child.once("exit", () => children.delete(child));
  return child;
}

export function killTree(child) {
  if (!child || child.exitCode !== null || child.signalCode !== null) return;
  try {
    if (process.platform === "win32") execFileSync("taskkill", ["/PID", String(child.pid), "/T", "/F"], { stdio: "ignore" });
    else process.kill(-child.pid, "SIGKILL");
  } catch {
    try { child.kill("SIGKILL"); } catch {}
  }
}

export function killAll() {
  for (const c of children) killTree(c);
}

// Spawn options so that killTree() can reach grandchildren on POSIX (process group).
export const groupSpawn = process.platform === "win32" ? {} : { detached: true };

export async function waitExit(child, timeout = 8000) {
  if (!child || child.exitCode !== null || child.signalCode !== null) return true;
  return Promise.race([new Promise((r) => child.once("exit", () => r(true))), sleep(timeout).then(() => false)]);
}

export function makeTempDir(label) {
  return fs.mkdtempSync(path.join(os.tmpdir(), `trackflow-ui-${label}-`));
}

export function removeDir(dir) {
  if (!dir) return true;
  try {
    fs.rmSync(dir, { recursive: true, force: true, maxRetries: 10, retryDelay: 300 });
  } catch {}
  return !fs.existsSync(dir);
}

export async function freePort() {
  const s = net.createServer();
  await new Promise((r) => s.listen(0, "127.0.0.1", r));
  const { port } = s.address();
  await new Promise((r) => s.close(r));
  return port;
}

// ------------------------------------------------------------------ static server (read-only)

const TYPES = {
  ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
  ".svg": "image/svg+xml", ".png": "image/png", ".json": "application/json",
};

// Same contract as the R4 servers: GET/HEAD only (anything else -> 405, body discarded), confined to root.
export async function startStaticServer(root) {
  const resolvedRoot = path.resolve(root);
  const log = [];
  const server = http.createServer((req, res) => {
    const u = new URL(req.url, "http://127.0.0.1");
    const done = (status) => log.push({ method: req.method, path: u.pathname, status });
    if (req.method !== "GET" && req.method !== "HEAD") {
      req.resume();
      res.writeHead(405).end();
      return done(405);
    }
    let p = decodeURIComponent(u.pathname);
    if (p.endsWith("/")) p += "index.html";
    const file = path.resolve(resolvedRoot, "." + p);
    if (!file.startsWith(resolvedRoot + path.sep)) {
      res.writeHead(403).end();
      return done(403);
    }
    fs.readFile(file, (err, buf) => {
      if (err) {
        res.writeHead(404).end();
        return done(404);
      }
      res.writeHead(200, { "Content-Type": TYPES[path.extname(file)] || "application/octet-stream", "Cache-Control": "no-store" });
      res.end(req.method === "HEAD" ? undefined : buf);
      done(200);
    });
  });
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  return {
    origin: `http://127.0.0.1:${server.address().port}`,
    log,
    close: () => new Promise((r) => { server.closeAllConnections?.(); server.close(() => r()); }),
  };
}

// ------------------------------------------------------------------ chrome + CDP

export function findChrome() {
  if (process.env.CHROME_PATH) return fs.existsSync(process.env.CHROME_PATH) ? process.env.CHROME_PATH : null;
  const candidates = process.platform === "win32"
    ? [
        path.join(process.env.PROGRAMFILES || "C:\\Program Files", "Google", "Chrome", "Application", "chrome.exe"),
        path.join(process.env["PROGRAMFILES(X86)"] || "C:\\Program Files (x86)", "Google", "Chrome", "Application", "chrome.exe"),
        path.join(process.env.LOCALAPPDATA || "", "Google", "Chrome", "Application", "chrome.exe"),
        path.join(process.env.PROGRAMFILES || "C:\\Program Files", "Chromium", "Application", "chrome.exe"),
      ]
    : process.platform === "darwin"
      ? ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/Applications/Chromium.app/Contents/MacOS/Chromium"]
      : ["/usr/bin/google-chrome", "/usr/bin/google-chrome-stable", "/usr/bin/chromium", "/usr/bin/chromium-browser"];
  return candidates.find((c) => c && fs.existsSync(c)) || null;
}

export async function launchChrome({ allowedHosts = [] } = {}) {
  const chromePath = findChrome();
  if (!chromePath) throw new Error("Chrome/Chromium not found. Set CHROME_PATH to the browser executable.");
  const profileDir = makeTempDir("chrome");
  const resolverRules = ["MAP * ~NOTFOUND", "EXCLUDE 127.0.0.1", ...allowedHosts.map((h) => `EXCLUDE ${h}`)].join(" , ");
  const proc = track(spawn(chromePath, [
    "--headless=new", "--remote-debugging-port=0", `--user-data-dir=${profileDir}`,
    "--no-first-run", "--no-default-browser-check", "--disable-background-networking",
    "--disable-component-update", "--disable-sync", "--disable-extensions", "--disable-default-apps",
    `--host-resolver-rules=${resolverRules}`, "--window-size=1280,900", "about:blank",
  ], { stdio: "ignore", ...groupSpawn }));

  const portFile = path.join(profileDir, "DevToolsActivePort");
  const wsUrl = await waitFor(() => {
    if (!fs.existsSync(portFile)) return null;
    const [p, wp] = fs.readFileSync(portFile, "utf8").split(/\r?\n/);
    return p && wp ? `ws://127.0.0.1:${p}${wp}` : null;
  }, 15000);
  if (!wsUrl) {
    killTree(proc);
    removeDir(profileDir);
    throw new Error("Chrome DevTools endpoint not available");
  }

  const ws = new WebSocket(wsUrl);
  let seq = 0;
  const pending = new Map();
  const handlers = new Set();
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.id && pending.has(msg.id)) {
      const { resolve, reject } = pending.get(msg.id);
      pending.delete(msg.id);
      msg.error ? reject(new Error(JSON.stringify(msg.error))) : resolve(msg.result);
    } else handlers.forEach((h) => h(msg));
  };
  const send = (method, params = {}, sessionId) => {
    const id = ++seq;
    ws.send(JSON.stringify({ id, method, params, sessionId }));
    return new Promise((resolve, reject) => pending.set(id, { resolve, reject }));
  };
  const version = (await send("Browser.getVersion")).product;

  return {
    version,
    send,
    handlers,
    async close() {
      await Promise.race([send("Browser.close").catch(() => {}), sleep(3000)]);
      try { ws.close(); } catch {}
      if (!(await waitExit(proc, 5000))) killTree(proc);
      await waitExit(proc, 5000);
      return { profileRemoved: removeDir(profileDir) };
    },
  };
}

// policy({ method, url: URL, resourceType }) -> true (continue) | false (fail before sending).
export async function openPage(browser, { policy, viewport = { width: 1280, height: 900, mobile: false } }) {
  const { send, handlers } = browser;
  const { targetId } = await send("Target.createTarget", { url: "about:blank" });
  const { sessionId } = await send("Target.attachToTarget", { targetId, flatten: true });
  const state = { requests: [], blocked: [], responses: [], exceptions: [], consoleErrors: [], loads: 0 };
  const urls = new Map();

  const handler = (msg) => {
    if (msg.sessionId !== sessionId) return;
    const p = msg.params;
    switch (msg.method) {
      case "Fetch.requestPaused": {
        const url = new URL(p.request.url);
        const entry = { method: p.request.method, host: url.host, path: url.pathname, type: p.resourceType };
        if (policy({ method: p.request.method, url, resourceType: p.resourceType })) {
          state.requests.push(entry);
          send("Fetch.continueRequest", { requestId: p.requestId }, sessionId).catch(() => {});
        } else {
          state.blocked.push(entry);
          send("Fetch.failRequest", { requestId: p.requestId, errorReason: "BlockedByClient" }, sessionId).catch(() => {});
        }
        break;
      }
      case "Network.requestWillBeSent":
        urls.set(p.requestId, p.request.url);
        break;
      case "Network.responseReceived": {
        const url = new URL(p.response.url);
        state.responses.push({ requestId: p.requestId, host: url.host, path: url.pathname, status: p.response.status, mimeType: p.response.mimeType, type: p.type });
        break;
      }
      case "Runtime.exceptionThrown": {
        const d = p.exceptionDetails;
        state.exceptions.push((d.exception?.description || d.text || "").split("\n")[0].slice(0, 200));
        break;
      }
      case "Runtime.consoleAPICalled":
        if (p.type === "error") state.consoleErrors.push(p.args.map((a) => a.value ?? a.description).join(" ").slice(0, 200));
        break;
      case "Page.loadEventFired":
        state.loads++;
        break;
    }
  };
  handlers.add(handler);

  await send("Fetch.enable", { patterns: [{ urlPattern: "*", requestStage: "Request" }] }, sessionId);
  for (const d of ["Runtime.enable", "Network.enable", "Page.enable", "DOM.enable"]) await send(d, {}, sessionId);
  await send("Network.setCacheDisabled", { cacheDisabled: true }, sessionId);
  await send("Emulation.setDeviceMetricsOverride", { width: viewport.width, height: viewport.height, deviceScaleFactor: 1, mobile: viewport.mobile }, sessionId);

  const evaluate = async (expression) => {
    const r = await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true }, sessionId);
    if (r.exceptionDetails) throw new Error("eval: " + String(r.exceptionDetails.exception?.description || r.exceptionDetails.text).slice(0, 200));
    return r.result.value;
  };

  return {
    sessionId,
    state,
    send: (method, params) => send(method, params, sessionId),
    eval: evaluate,
    async goto(url, timeout = 20000) {
      const before = state.loads;
      const nav = await send("Page.navigate", { url }, sessionId);
      const loaded = !!(await waitFor(() => state.loads > before, timeout, 50));
      return { loaded, navigationError: nav.errorText || null };
    },
    async setFile(selector, filePath) {
      const { root } = await send("DOM.getDocument", {}, sessionId);
      const { nodeId } = await send("DOM.querySelector", { nodeId: root.nodeId, selector }, sessionId);
      await send("DOM.setFileInputFiles", { nodeId, files: [path.resolve(filePath)] }, sessionId);
    },
    async close() {
      handlers.delete(handler);
      await send("Target.closeTarget", { targetId }).catch(() => {});
    },
  };
}

// ------------------------------------------------------------------ DOM probe helpers (page side)

// vis(): present + effectively visible (display/visibility/opacity on self and ancestors, non-zero box).
// hiddenAudit(): every `.hidden` element must compute to display:none unless it carries a responsive
// override (`hidden md:block` etc.) — the invariant R4-C3 demonstrated online.
export const PAGE_HELPERS = `const q=(s)=>document.querySelector(s);const qa=(s)=>[...document.querySelectorAll(s)];
const txt=(s)=>((typeof s==='string'?q(s):s)?.textContent||'').trim().replace(/\\s+/g,' ');
const cs=(el)=>getComputedStyle(el);
const vis=(s)=>{const el=typeof s==='string'?q(s):s;if(!el)return {present:false,visible:false};const c=cs(el);const r=el.getBoundingClientRect();
  let v=c.display!=='none'&&c.visibility!=='hidden'&&Number(c.opacity)>0&&r.width>0&&r.height>0;
  for(let p=el.parentElement;p&&v;p=p.parentElement){const pc=cs(p);if(pc.display==='none'||pc.visibility==='hidden'||Number(pc.opacity)===0)v=false;}
  return {present:true,visible:v,display:c.display}};
const hiddenAudit=()=>{const els=qa('.hidden');const resp=/(^|\\s)(sm|md|lg|xl|2xl):(block|flex|grid|inline|inline-block|inline-flex|table)(\\s|$)/;
  const shown=els.filter(e=>cs(e).display!=='none');
  return {hidden_class_elements:els.length,computed_display_none:els.length-shown.length,
    shown_with_responsive_override:shown.filter(e=>resp.test(e.className)).length,
    shown_without_responsive_override:shown.filter(e=>!resp.test(e.className)).map(e=>e.tagName.toLowerCase()+(e.id?'#'+e.id:''))}};
const overflowX=()=>Math.max(0,document.documentElement.scrollWidth-window.innerWidth);
const tailwindReady=()=>typeof window.tailwind!=='undefined'&&[...document.querySelectorAll('style')].some(s=>/--tw-/.test(s.textContent));`;
