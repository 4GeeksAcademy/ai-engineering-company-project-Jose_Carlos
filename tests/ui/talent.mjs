// Talent Pipeline Tracker baseline (BP-5) — derived from audit R4-D talent_ui_checks_v2.mjs and
// talent_ui_createform_enum_scan.mjs. STRICTLY READ-ONLY against the external Talent API.
//
// Safety:
//  * Own `next dev` bound to 127.0.0.1 on a free port (NEXT_TELEMETRY_DISABLED=1), killed at the end.
//  * Every browser request goes through a CDP Fetch guard and is failed BEFORE leaving the machine unless:
//      - 127.0.0.1 GET/HEAD, or non-GET to Next dev internals (/_next/*, /__nextjs*) only;
//      - playground.4geeks.com GET/HEAD only (POST/PUT/PATCH/DELETE/OPTIONS are blocked and fail the run).
//    Any other host is blocked. DNS resolves only 127.0.0.1 and the Talent API host.
//  * All Talent API calls in this app are client-side (app/lib/api.ts from client components); the
//    Next route handlers only touch the local photo directory, and only GET /api/profile-photo is used.
//  * No write-capable control is used: no create submit, no detail Estado/Etapa change, no edit, no
//    delete, no notes, no photo upload (TALENT-006..011 are out of scope).
//
// Privacy:
//  * API bodies are kept in memory only, to compare against the DOM. Nothing is written to disk.
//  * Reported details contain only counts, booleans, enum labels and path templates. Before printing,
//    every detail is redacted against all personal values seen (names, emails, phones, URLs, ids,
//    note contents, search fragment) and UUIDs; the suite fails closed if anything would leak.
//  * No screenshots. next dev output stays in memory and is shown only (UUID-redacted) on startup failure.

import fs from "node:fs";
import path from "node:path";
import { spawn } from "node:child_process";
import { Recorder, freePort, groupSpawn, killTree, launchChrome, openPage, sleep, track, waitExit, waitFor } from "./lib/harness.mjs";

const API_HOST = "playground.4geeks.com";
const API_PREFIX = "/tracker/api/v1";
const UUID_RE = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi;
const ZERO_ID = "00000000-0000-0000-0000-000000000000";
// AS-IS labels (app/lib/constants.ts). F-13: U-L1 is expected to change 5 of them deliberately;
// update these together with that unit.
const STATUS_LABELS = { received: "Recibido", in_progress: "En proceso", selected: "Seleccionado", discarded: "Descartado" };
const STAGE_LABELS = { pending: "Pendiente", review: "Revisión", personal_interview: "Entrevista personal", technical_interview: "Entrevista técnica", offer_presented: "Oferta presentada" };
const RAW_VALUES = [...Object.keys(STATUS_LABELS), ...Object.keys(STAGE_LABELS)];
const ALL_LABELS = [...Object.values(STATUS_LABELS), ...Object.values(STAGE_LABELS)];

// ------------------------------------------------------------------ privacy

const sensitive = new Set();
function collectSensitive(body) {
  const add = (v) => { if (typeof v === "string" && v.trim().length >= 3) sensitive.add(v.trim()); };
  const rec = (r) => {
    if (!r || typeof r !== "object") return;
    ["id", "full_name", "email", "phone", "position", "linkedin_url", "cv_url", "photo_url"].forEach((k) => add(r[k]));
    (Array.isArray(r.notes) ? r.notes : []).forEach((n) => { add(n?.content); add(n?.id); });
  };
  if (Array.isArray(body?.data)) body.data.forEach((x) => { rec(x); add(x?.content); add(x?.id); });
  else rec(body);
}
const tpl = (p) => p.replace(UUID_RE, "{id}");
function redact(value) {
  const list = [...sensitive].sort((a, b) => b.length - a.length);
  const clean = (v) => {
    if (typeof v === "string") {
      let s = v;
      for (const x of list) if (s.includes(x)) s = s.split(x).join("<redacted>");
      return s.replace(UUID_RE, (m) => (m === ZERO_ID ? m : "{id}"));
    }
    if (Array.isArray(v)) return v.map(clean);
    if (v && typeof v === "object") return Object.fromEntries(Object.entries(v).map(([k, x]) => [clean(k), clean(x)]));
    return v;
  };
  return clean(value);
}
const leaks = (text) => [...sensitive].filter((x) => text.includes(x)).length + (text.match(UUID_RE) || []).filter((m) => m !== ZERO_ID).length;

class PrivateRecorder extends Recorder {
  check(id, description, ok, detail, kind) {
    return super.check(id, description, ok, detail === undefined ? undefined : redact(detail), kind);
  }
}

// ------------------------------------------------------------------ next dev

async function startNextDev(talentDir) {
  const nextBin = path.join(talentDir, "node_modules", "next", "dist", "bin", "next");
  if (!fs.existsSync(nextBin)) throw new Error("Tracker dependencies missing: run `npm ci` in uis/talent-pipeline-tracker first.");
  const port = await freePort();
  const output = [];
  const proc = track(spawn(process.execPath, [nextBin, "dev", "--port", String(port), "--hostname", "127.0.0.1"], {
    cwd: talentDir,
    env: { ...process.env, NEXT_TELEMETRY_DISABLED: "1" },
    stdio: ["ignore", "pipe", "pipe"],
    ...groupSpawn,
  }));
  for (const s of [proc.stdout, proc.stderr]) s.on("data", (b) => { output.push(String(b)); if (output.length > 200) output.shift(); });
  const origin = `http://127.0.0.1:${port}`;
  const ready = await waitFor(async () => (await fetch(origin + "/favicon.ico", { method: "HEAD" })).status > 0, 120000, 500);
  if (!ready) {
    killTree(proc);
    throw new Error("next dev did not become ready: " + output.join("").replace(UUID_RE, "{id}").slice(-800));
  }
  return { proc, origin, output };
}

// ------------------------------------------------------------------ page-side helpers

const HELP = `
const $=(s,r=document)=>r.querySelector(s); const $$=(s,r=document)=>[...r.querySelectorAll(s)];
const T=(el)=>(el?.textContent||'').trim().replace(/\\s+/g,' ');
const listState=()=>{const main=$('main');const loading=/Cargando candidaturas/.test(T(main));
  const cards=$$('main .space-y-3 > button').map(b=>({name:T($('h2',b)),position:T($('article p',b)),badges:$$('span.rounded-full',b).map(T)}));
  const pageLbl=$$('main span').map(T).find(t=>/^Página \\d+ de \\d+$/.test(t))||null;
  const total=T($('main p strong'));const empty=/No hay candidaturas/.test(T(main));const err=/No se pudo cargar el listado/.test(T(main));
  return {loading,cards,pageLbl,total,empty,err};};
const setSelect=(idx,v)=>{const s=$$('nav select')[idx];Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,'value').set.call(s,v);s.dispatchEvent(new Event('change',{bubbles:true}));return true;};
const setSearch=(v)=>{const i=$('nav input');Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(i,v);i.dispatchEvent(new Event('input',{bubbles:true}));return true;};
const btn=(t)=>$$('button').find(b=>T(b)===t);
`;

export async function run({ repoRoot }) {
  const rec = new PrivateRecorder("talent");
  const talentDir = path.join(repoRoot, "uis", "talent-pipeline-tracker");
  const api = { requests: [], bodies: new Map(), writeAttempts: [], blocked: [], otherHosts: new Set(), localNonGet: [] };
  let dev = null;
  let browser = null;
  let cleanup = {};

  const policy = ({ method, url }) => {
    const read = method === "GET" || method === "HEAD";
    if (url.hostname === "127.0.0.1") {
      if (read) return true;
      if (url.pathname.startsWith("/_next/") || url.pathname.startsWith("/__nextjs")) { api.localNonGet.push({ method, path: tpl(url.pathname) }); return true; }
      api.blocked.push({ method, host: "127.0.0.1", path: tpl(url.pathname) });
      return false;
    }
    if (url.hostname === API_HOST) {
      if (read) return true;
      api.writeAttempts.push({ method, path: tpl(url.pathname) });
      return false;
    }
    api.otherHosts.add(url.host);
    api.blocked.push({ method, host: url.host, path: tpl(url.pathname) });
    return false;
  };

  try {
    dev = await startNextDev(talentDir);
    browser = await launchChrome({ allowedHosts: [API_HOST] });
    const page = await openPage(browser, { policy });
    const sid = page.sessionId;

    // Talent API bookkeeping: method/path/status + JSON body in memory for DOM comparison.
    const meta = new Map();
    browser.handlers.add((msg) => {
      if (msg.sessionId !== sid) return;
      const p = msg.params;
      if (msg.method === "Network.requestWillBeSent") {
        const u = new URL(p.request.url);
        if (u.hostname === API_HOST && u.pathname.startsWith(API_PREFIX)) {
          const e = { rid: p.requestId, method: p.request.method, path: u.pathname.slice(API_PREFIX.length), url: u, status: null, done: false };
          meta.set(p.requestId, e);
          api.requests.push(e);
        }
      } else if (msg.method === "Network.responseReceived") {
        const e = meta.get(p.requestId);
        if (e) e.status = p.response.status;
      } else if (msg.method === "Network.loadingFinished") {
        const e = meta.get(p.requestId);
        if (e) browser.send("Network.getResponseBody", { requestId: p.requestId }, sid)
          .then((b) => { try { const j = JSON.parse(b.body); collectSensitive(j); api.bodies.set(p.requestId, j); } catch {} e.done = true; })
          .catch(() => { e.done = true; });
      } else if (msg.method === "Network.loadingFailed") {
        const e = meta.get(p.requestId);
        if (e) { e.done = true; e.failed = true; }
      }
    });

    const ev = page.eval;
    const qp = (e, k) => e.url.searchParams.get(k);
    const listState = () => ev(`(()=>{${HELP};return listState()})()`);
    const urlParams = () => ev(`(()=>{const p=new URLSearchParams(location.search);return {status:p.get('status')??'',stage:p.get('stage')??'',search:p.get('search')??'',page:Number(p.get('page')??'1'),path:location.pathname}})()`);

    // Wait until the DOM renders exactly (all names, in order) the body of a GET /records issued after `since`
    // with the expected params, and the URL carries the same params (R4-D pass-2 synchronisation rule).
    async function waitList(expect, since) {
      const want = { status: expect.status ?? "", stage: expect.stage ?? "", search: expect.search ?? "", page: expect.page ?? 1 };
      const match = (e) => e.method === "GET" && e.path === "/records" && (qp(e, "status") ?? "") === want.status && (qp(e, "stage") ?? "") === want.stage &&
        (qp(e, "search") ?? "") === want.search && Number(qp(e, "page") ?? "1") === want.page;
      const urlOk = !!(await waitFor(async () => { const u = await urlParams(); return u.path === "/" && u.status === want.status && u.stage === want.stage && u.search === want.search && u.page === want.page; }, 20000));
      const found = await waitFor(async () => {
        const s = await listState();
        if (s.loading || s.err) return null;
        for (let i = api.requests.length - 1; i >= since; i--) {
          const e = api.requests[i];
          if (!e.done || !match(e) || !api.bodies.has(e.rid)) continue;
          const b = api.bodies.get(e.rid);
          const d = b?.data || [];
          const ok = d.length === 0 ? s.empty : s.cards.length === d.length && s.cards.every((c, k) => c.name === d[k].full_name);
          if (ok) return { e, b, s };
        }
        return null;
      }, 45000);
      if (!found) return { ok: false, urlOk, req: null, body: null, dom: await listState() };
      return { ok: true, urlOk, req: found.e, body: found.b, dom: found.s };
    }
    let marker = null;
    const setMarker = async () => { marker = `ua5-${Date.now()}-${Math.random()}`; await ev(`window.__ua5Marker=${JSON.stringify(marker)};true`); };
    const noReload = async () => (await ev("window.__ua5Marker||null")) === marker;
    async function act(expr, expect) {
      const since = api.requests.length;
      await ev(`(()=>{${HELP};${expr};return true})()`);
      return waitList(expect, since);
    }
    async function cleanStart() {
      const since = api.requests.length;
      await page.goto(dev.origin + "/", 60000);
      const r = await waitList({}, since);
      await setMarker();
      return r;
    }
    const synced = (r) => r.ok && r.urlOk;
    const cardsMatch = (dom, body) => {
      const d = body?.data || [];
      return dom.cards.length === d.length && dom.cards.every((c, i) => c.name === d[i].full_name && c.position === d[i].position &&
        c.badges[0] === STATUS_LABELS[d[i].status] && c.badges[1] === STAGE_LABELS[d[i].stage]);
    };
    async function rawScan() {
      return ev(`(()=>{const txt=document.body.innerText;const opts=[...document.querySelectorAll('select')].map(s=>[...s.options].map(o=>o.text).join('|')).join('||');
        const raw=${JSON.stringify(RAW_VALUES)};const L=${JSON.stringify(ALL_LABELS)};
        const rawVisible=raw.filter(v=>{const re=new RegExp('(^|[^A-Za-z_])'+v+'([^A-Za-z_]|$)');return re.test(txt)||re.test(opts)});
        return {raw_values_visible:rawVisible,labels_missing:L.filter(l=>!txt.includes(l))}})()`);
    }

    // ============================================================ TALENT-001 pagination
    const start = await cleanStart();
    if (!start.ok) throw new Error("initial list did not load from the Talent API (network/API unavailable?)");
    const base = start.body;
    const total = base.total, limit = base.limit, pages = Math.max(1, Math.ceil(total / limit));
    rec.check("TAL-001-01", "initial list = GET /records?page=1&limit=12 (200), rendered cards equal the response",
      synced(start) && start.req.status === 200 && Number(qp(start.req, "page")) === 1 && Number(qp(start.req, "limit")) === 12 && cardsMatch(start.dom, base),
      { synced: synced(start), status: start.req?.status, limit: qp(start.req, "limit"), rendered: start.dom.cards.length });
    rec.check("TAL-001-02", "total label equals API total; page label 'Página 1 de N' with N = ceil(total/limit); Anterior disabled",
      Number(start.dom.total) === total && start.dom.pageLbl === `Página 1 de ${pages}` && (await ev(`(()=>{${HELP};return btn('Anterior').disabled})()`)),
      { api_total: total, api_limit: limit, page_label: start.dom.pageLbl });
    const ids = new Set(base.data.map((r) => r.id));
    let sum = start.dom.cards.length, dup = 0, stepsOk = true;
    const stepIssues = [];
    for (let pg = 2; pg <= pages; pg++) {
      const r = await act(`btn('Siguiente').click()`, { page: pg });
      (r.body?.data || []).forEach((x) => { if (ids.has(x.id)) dup++; ids.add(x.id); });
      sum += r.dom.cards.length;
      const ok = synced(r) && r.req.status === 200 && r.dom.pageLbl === `Página ${pg} de ${pages}` && cardsMatch(r.dom, r.body) && (await noReload());
      if (!ok) { stepsOk = false; stepIssues.push({ page: pg, synced: synced(r), page_label: r.dom.pageLbl }); }
    }
    rec.check("TAL-001-03", "Siguiente walks every page in place (URL ?page=n, GET page=n, labels, cards = response, no reload)", stepsOk, { pages, issues: stepIssues });
    const nextDisabled = await ev(`(()=>{${HELP};return btn('Siguiente').disabled})()`);
    rec.check("TAL-001-04", "sum of rendered cards = API total, all ids distinct, Siguiente disabled on last page",
      sum === total && ids.size === total && dup === 0 && nextDisabled, { sum, total, distinct: ids.size, dup, next_disabled_last: nextDisabled });
    if (pages > 1) {
      const back = await act(`btn('Anterior').click()`, { page: pages - 1 });
      rec.check("TAL-001-05", "Anterior goes back one page in place", synced(back) && back.dom.pageLbl === `Página ${pages - 1} de ${pages}` && (await noReload()), { page_label: back.dom.pageLbl });
    }

    // ============================================================ TALENT-002 status filter (first change from page > 1)
    {
      const issues = [];
      for (const v of Object.keys(STATUS_LABELS)) {
        const r = await act(`setSelect(0,'${v}')`, { status: v, page: 1 });
        const d = r.body?.data || [];
        const ok = synced(r) && r.req.status === 200 && qp(r.req, "status") === v && Number(qp(r.req, "page") ?? 1) === 1 &&
          Number(r.dom.total) === r.body.total && d.every((x) => x.status === v) && r.dom.cards.every((c) => c.badges[0] === STATUS_LABELS[v]) &&
          (d.length === 0 ? r.dom.empty : cardsMatch(r.dom, r.body)) && (await noReload());
        rec.check(`TAL-002-${v}`, `status filter '${STATUS_LABELS[v]}': GET ?status=${v}&page=1, every card/item matches, total label = API total`, ok,
          { synced: synced(r), api_total: r.body?.total ?? null, rendered: r.dom.cards.length, empty_state: r.dom.empty });
        if (!ok) issues.push(v);
      }
      const reset = await act(`setSelect(0,'')`, {});
      rec.check("TAL-002-reset", "status 'Todos' restores the unfiltered list (total = unfiltered total)", synced(reset) && reset.body.total === total && (await noReload()), { api_total: reset.body?.total ?? null });
    }

    // ============================================================ TALENT-003 stage filter + combination
    {
      for (const v of Object.keys(STAGE_LABELS)) {
        const r = await act(`setSelect(1,'${v}')`, { stage: v, page: 1 });
        const d = r.body?.data || [];
        const ok = synced(r) && r.req.status === 200 && qp(r.req, "stage") === v && Number(r.dom.total) === r.body.total &&
          d.every((x) => x.stage === v) && r.dom.cards.every((c) => c.badges[1] === STAGE_LABELS[v]) &&
          (d.length === 0 ? r.dom.empty : cardsMatch(r.dom, r.body)) && (await noReload());
        rec.check(`TAL-003-${v}`, `stage filter '${STAGE_LABELS[v]}': GET ?stage=${v}, every card/item matches, total label = API total`, ok,
          { synced: synced(r), api_total: r.body?.total ?? null, rendered: r.dom.cards.length, empty_state: r.dom.empty });
      }
      await act(`setSelect(1,'pending')`, { stage: "pending" });
      const rc = await act(`setSelect(0,'received')`, { status: "received", stage: "pending" });
      const d = rc.body?.data || [];
      rec.check("TAL-003-combined", "status + stage combine: GET carries both params, every item/card is Recibido + Pendiente",
        synced(rc) && qp(rc.req, "status") === "received" && qp(rc.req, "stage") === "pending" && d.every((x) => x.status === "received" && x.stage === "pending") &&
          rc.dom.cards.every((c) => c.badges[0] === "Recibido" && c.badges[1] === "Pendiente") && (d.length === 0 ? rc.dom.empty : cardsMatch(rc.dom, rc.body)) && (await noReload()),
        { synced: synced(rc), api_total: rc.body?.total ?? null, rendered: rc.dom.cards.length });
      const c1 = await act(`setSelect(0,'')`, { stage: "pending" });
      const c2 = await act(`setSelect(1,'')`, {});
      rec.check("TAL-003-reset", "clearing both filters restores the unfiltered list and a clean URL",
        synced(c1) && synced(c2) && c2.body.total === total && (await ev("location.search")) === "", { api_total: c2.body?.total ?? null });
    }

    // ============================================================ TALENT-014 / 015 on the list
    {
      const c = await cleanStart();
      const scanList = await rawScan();
      rec.check("TAL-014-list", "list: no raw enum value visible (text or select options); all 9 labels present", synced(c) && scanList.raw_values_visible.length === 0 && scanList.labels_missing.length === 0, scanList);
      await act(`setSelect(0,'in_progress')`, { status: "in_progress" });
      const g = await act(`setSelect(1,'review')`, { status: "in_progress", stage: "review" });
      const scanF = await rawScan();
      rec.check("TAL-014-filtered", "filtered list: no raw enum value visible", synced(g) && scanF.raw_values_visible.length === 0, scanF);

      const c2 = await cleanStart();
      const contents = (c2.body?.data || []).flatMap((r) => (Array.isArray(r.notes) ? r.notes : []).map((n) => n?.content))
        .filter((x) => typeof x === "string" && x.trim().length >= 8).map((x) => x.trim());
      const hits = await ev(`(()=>{const t=document.body.innerText;const c=${JSON.stringify(contents)};return c.filter(x=>t.includes(x)).length})()`);
      rec.check("TAL-015-list", "notes delivered in the list response are NOT visible in the list (F-16 observation kept)",
        synced(c2) && hits === 0, { note_contents_in_response: contents.length, visible_in_list: hits });

      // Create form (TALENT-014, R4-D pass 3): open and close only — never submitted.
      const before = api.requests.length;
      await ev(`(()=>{${HELP};btn('Nueva candidatura').click();return true})()`);
      const form = await waitFor(() => ev(`(()=>{const f=document.querySelector('nav form');if(!f)return null;const txt=f.innerText;
        const sels=[...f.querySelectorAll('select')];const opt=sels.map(s=>[...s.options].map(o=>o.text).join('|')).join('||');
        const raw=${JSON.stringify(RAW_VALUES)};const L=${JSON.stringify(ALL_LABELS)};
        return {selects:sels.length,shown:sels.map(s=>s.options[s.selectedIndex]?.text),all_labels_in_options:L.every(l=>opt.includes(l)),
          raw_values_visible:raw.filter(v=>{const re=new RegExp('(^|[^A-Za-z_])'+v+'([^A-Za-z_]|$)');return re.test(txt)||re.test(opt)})}})()`), 5000);
      const reqsOnOpen = api.requests.length - before;
      await ev(`(()=>{${HELP};btn('Cerrar formulario').click();return true})()`);
      const closed = await waitFor(() => ev(`!document.querySelector('nav form')`), 5000);
      rec.check("TAL-014-createform", "create form (opened/closed, never submitted): 2 selects default Recibido/Pendiente, labels only, 0 API requests",
        !!form && form.selects === 2 && form.shown[0] === "Recibido" && form.shown[1] === "Pendiente" && form.all_labels_in_options && form.raw_values_visible.length === 0 && reqsOnOpen === 0 && !!closed,
        { ...(form || { open: false }), api_requests_on_open: reqsOnOpen, closed: !!closed });
    }

    // ============================================================ TALENT-004 search by name
    {
      const target = base.data.find((r) => typeof r.full_name === "string" && r.full_name.trim().split(/\s+/)[0].length >= 3);
      if (!target) throw new Error("no record with a usable first name for the search check");
      const frag = target.full_name.trim().split(/\s+/)[0];
      sensitive.add(frag);
      const fl = frag.toLowerCase();

      const single = async (text) => {
        await cleanStart();
        const since = api.requests.length;
        await ev(`document.querySelector('nav input').focus();true`);
        await page.send("Input.insertText", { text });
        const r = await waitList({ search: text, page: 1 }, since);
        return { r, ids: new Set((r.body?.data || []).map((x) => x.id)),
          ok: synced(r) && r.req.status === 200 && Number(r.dom.total) === r.body.total && r.dom.cards.length > 0 &&
            r.dom.cards.every((c) => c.name.toLowerCase().includes(fl)) && r.dom.cards.some((c) => c.name === target.full_name) && (await noReload()) };
      };
      const a = await single(frag);
      rec.check("TAL-004-search", "search by first name: GET ?search=, every rendered name contains it (case-insensitive), source record listed",
        a.ok, { fragment_length: frag.length, api_total: a.r.body?.total ?? null, rendered: a.r.dom.cards.length });
      const b = await single(frag.toUpperCase());
      rec.check("TAL-004-case", "upper-cased query returns the same result set (case-insensitive)",
        b.ok && a.ids.size === b.ids.size && [...b.ids].every((x) => a.ids.has(x)), { rendered: b.r.dom.cards.length });

      // Character-by-character typing (one input event per character): nothing lost.
      await cleanStart();
      const since = api.requests.length;
      await ev(`document.querySelector('nav input').focus();true`);
      for (const ch of frag) { await page.send("Input.insertText", { text: ch }); await sleep(150); }
      const typed = await waitList({ search: frag, page: 1 }, since);
      const st = await ev(`(()=>{const i=document.querySelector('nav input');return {input_equals:i.value===${JSON.stringify(frag)},url_equals:new URLSearchParams(location.search).get('search')===${JSON.stringify(frag)}}})()`);
      rec.check("TAL-004-typing", "typing the query char by char ends with input, URL and list all matching the full query",
        st.input_equals && st.url_equals && synced(typed) && (await noReload()), { ...st, synced: synced(typed) });
      const clr = await act(`setSearch('')`, {});
      rec.check("TAL-004-clear", "clearing the search restores the unfiltered list", synced(clr) && clr.body.total === total, { api_total: clr.body?.total ?? null });
    }

    // ============================================================ TALENT-005 detail + TALENT-015/014 detail
    {
      const cur = await cleanStart();
      const idx = Math.min(1, cur.dom.cards.length - 1);
      const clickedName = cur.dom.cards[idx]?.name;
      const expected = cur.body.data[idx];
      const since = api.requests.length;
      const loadsBefore = page.state.loads;
      await ev(`document.querySelectorAll('main .space-y-3 > button')[${idx}].click();true`);
      const detail = await waitFor(async () => {
        const s = await ev(`(()=>{const ps=[...document.querySelectorAll('main p')];const val=(lbl)=>{const p=ps.find(x=>x.querySelector('strong')?.textContent.trim()===lbl);return p?p.textContent.replace(lbl,'').trim():null};
          const notesSec=[...document.querySelectorAll('section')].find(s=>s.querySelector('h2')?.textContent.trim()==='Notas internas');
          return {path:location.pathname,name:val('Nombre:'),email:val('Email:'),loadingNotes:/Cargando notas/.test(document.body.innerText),
            notesSection:!!notesSec,noteTexts:notesSec?[...notesSec.querySelectorAll('p.note-clamp')].map(p=>p.textContent.trim()):[]}})()`);
        return s.name && !s.loadingNotes ? s : null;
      }, 45000);
      const urlId = detail?.path?.startsWith("/records/") ? decodeURIComponent(detail.path.slice(9)) : null;
      const newReqs = api.requests.slice(since);
      const detailReqs = newReqs.filter((e) => /^\/records\/[^/]+$/.test(e.path));
      const notesReqs = newReqs.filter((e) => /^\/records\/[^/]+\/notes$/.test(e.path));
      rec.check("TAL-005-nav", "clicking a card navigates in place to /records/{id} of that record",
        urlId === expected?.id && page.state.loads === loadsBefore && (await noReload()), { url_is_clicked_record: urlId === expected?.id, full_reload: page.state.loads !== loadsBefore });
      rec.check("TAL-005-detail", "detail fetched only for that id (GET 200 record + notes); name/email equal the clicked record",
        detailReqs.length > 0 && detailReqs.every((e) => e.path === `/records/${urlId}` && e.status === 200) && notesReqs.length > 0 && notesReqs.every((e) => e.path === `/records/${urlId}/notes`) &&
          detail?.name === clickedName && detail?.email === expected?.email,
        { detail_gets: detailReqs.length, notes_gets: notesReqs.length, name_matches: detail?.name === clickedName, email_matches: detail?.email === expected?.email });

      const notesReq = await waitFor(() => [...notesReqs].reverse().find((e) => e.done && api.bodies.has(e.rid)), 5000);
      const nContents = (notesReq ? api.bodies.get(notesReq.rid)?.data || [] : []).map((n) => n?.content).filter((c) => typeof c === "string" && c.trim()).map((c) => c.trim());
      rec.check("TAL-015-detail", "detail shows the 'Notas internas' section with exactly the API notes, in order",
        !!notesReq && !!detail?.notesSection && detail.noteTexts.length === nContents.length && detail.noteTexts.every((x, i) => x === nContents[i]),
        { notes_in_api: nContents.length, rendered_notes: detail?.noteTexts.length ?? 0 });
      const scanD = await rawScan();
      rec.check("TAL-014-detail", "detail: no raw enum value visible (text or select options)", scanD.raw_values_visible.length === 0, { raw_values_visible: scanD.raw_values_visible });
      const photo = page.state.responses.find((x) => x.host.startsWith("127.0.0.1") && x.path === `/api/profile-photo/${urlId}`);
      rec.check("TAL-005-photo", "detail loads the profile photo through local GET /api/profile-photo/{id} (200 image)",
        photo?.status === 200 && /^image\//.test(photo.mimeType), { status: photo?.status ?? null, mime: photo?.mimeType ?? null });

      const since2 = api.requests.length;
      await ev(`[...document.querySelectorAll('a')].find(a=>a.textContent.includes('Volver al listado')).click();true`);
      const back = await waitList({}, since2);
      rec.check("TAL-005-back", "'Volver al listado' returns to the list in place", synced(back) && back.dom.cards.length > 0 && (await noReload()), { synced: synced(back) });

      const since3 = api.requests.length;
      await page.goto(`${dev.origin}/records/${ZERO_ID}`, 60000);
      const nx = await waitFor(() => ev(`(()=>{const t=document.body.innerText;return /Ocurrió un error/.test(t)?{error_visible:true,http_404:/Error 404/.test(t),still_loading:/Cargando detalle/.test(t)}:null})()`), 45000);
      const nxReq = api.requests.slice(since3).find((e) => e.path === `/records/${ZERO_ID}`);
      rec.check("TAL-005-404", "non-existent id: GET /records/{id} -> 404 and a controlled 'Ocurrió un error … Error 404' message",
        nxReq?.status === 404 && nx?.error_visible && nx.http_404 && !nx.still_loading, { get_status: nxReq?.status ?? null, ...(nx || { error_visible: false }) });
    }

    // ============================================================ safety summary
    const byTemplate = {};
    for (const e of api.requests) byTemplate[`${e.method} ${tpl(e.path)}`] = (byTemplate[`${e.method} ${tpl(e.path)}`] || 0) + 1;
    rec.endpoints = byTemplate;
    rec.check("TAL-SAFE-01", "Talent API: GET/HEAD only — zero write attempts (POST/PUT/PATCH/DELETE/OPTIONS)",
      api.writeAttempts.length === 0 && api.requests.every((e) => e.method === "GET" || e.method === "HEAD"), { endpoints: byTemplate, write_attempts: api.writeAttempts });
    rec.check("TAL-SAFE-02", "no request to any other external host; no local non-GET outside Next internals",
      api.otherHosts.size === 0 && api.blocked.length === 0, { other_hosts: [...api.otherHosts], blocked: api.blocked, local_non_get_next_internals: api.localNonGet.length });
    rec.check("TAL-SAFE-03", "0 uncaught exceptions in the tracker pages", page.state.exceptions.length === 0, { exceptions: page.state.exceptions.length });
    await page.close();
  } catch (e) {
    rec.abort(e);
  } finally {
    if (browser) cleanup = await browser.close();
    if (dev) {
      killTree(dev.proc);
      cleanup.nextStopped = await waitExit(dev.proc, 8000);
    }
  }
  rec.check("TAL-CLEAN", "next dev stopped and temporary Chrome profile removed", (browser ? cleanup.profileRemoved : true) && (dev ? cleanup.nextStopped : true), cleanup);

  // Fail closed: nothing that left this suite may contain a personal value or a record UUID.
  const printed = JSON.stringify(rec.checks) + JSON.stringify(rec.endpoints || {});
  const residual = leaks(printed);
  rec.check("TAL-PRIVACY", `reported output contains no personal values or record ids (${sensitive.size} tracked in memory)`, residual === 0, { residual_hits: residual });
  if (rec.endpoints) console.log(`  Talent API endpoints used: ${JSON.stringify(rec.endpoints)}`);
  sensitive.clear();
  return rec;
}
