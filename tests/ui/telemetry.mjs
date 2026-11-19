// Telemetría del backoffice (hitos 15 y 16) en un navegador real: lo mismo que se ve en la pestaña
// Network de DevTools, y después lo que ha quedado en la tabla telemetry_events.
//
// Arranca la API (con la ingesta real POST /telemetry/events) y el backoffice con
// NEXT_PUBLIC_TELEMETRY_ENDPOINT apuntando a ella, recorre un flujo de inventario (login fallido,
// login, entrada, salida rechazada, salida correcta, formulario abandonado, error de JavaScript,
// intento de fijar stock con PUT, cerrar la pestaña) y comprueba:
//
//  * en la red: lotes, 200 a todos (fetch y sendBeacon), esquemas, sin PII, X-Request-Id;
//  * en la tabla (hito 16): cada evento enviado está guardado una vez, con event_type, timestamp y
//    tags correctos, tanto los de negocio como los técnicos y los que emite la propia API;
//  * el rechazo individual: un lote mixto devuelve stored/rejected correctos y solo guarda los válidos.
//
// Por defecto la API usa un SQLite desechable. Con TELEMETRY_E2E_SUPABASE=1 usa el DATABASE_URL del
// .env (Supabase): es la verificación end-to-end del hito 16. Deja en Supabase un SKU de prueba
// (código E2E-TEL-…), sus dos movimientos y las filas de telemetría, que son inmutables.

import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { PAGE_HELPERS, Recorder, killTree, launchChrome, makeTempDir, openPage, removeDir, waitExit, waitFor } from "./lib/harness.mjs";
import { apiCall, createUser, disposableDatabaseUrl, setValue, startStack, submit } from "./lib/backoffice-app.mjs";

const ON_SUPABASE = process.env.TELEMETRY_E2E_SUPABASE === "1";
// Código único por ejecución: en Supabase el SKU de la ejecución anterior sigue ahí.
const SKU_CODE = `E2E-TEL-${Date.now().toString(36).toUpperCase()}`;

const EMAIL = "telemetria-ui@trackflow.com";
const PASSWORD = "telemetria-ui-1234";
const WRONG_PASSWORD = "contraseña-equivocada-77";
const REFERENCE = "PO-TEL-0042";

const EXPECTED_TYPES = [
  "login_failed",
  "page_viewed",
  "inbound_order_created",
  "outbound_order_rejected",
  "outbound_order_created",
  "order_form_abandoned",
  "frontend_error_captured",
  "page_load_recorded",
];

async function seed(origin) {
  const { token } = await createUser(origin, EMAIL, PASSWORD);
  const sku = await apiCall(origin, "POST", "/inventory/products", {
    token, body: { name: "Auriculares inalámbricos Pro (prueba E2E de telemetría)", sku: SKU_CODE, client_name: "SoundWave Electronics", category: "electronics", warehouse: "LA" },
  });
  await apiCall(origin, "POST", "/inventory/orders/inbound", { token, body: { sku_id: sku.id, quantity: 20, warehouse: "LA", reference: "PO-2024-0112" } });
  return { sku, token };
}

function python(repoRoot) {
  return process.env.PYTHON || [path.join(repoRoot, ".venv", "Scripts", "python.exe"), path.join(repoRoot, ".venv", "bin", "python")].find((p) => fs.existsSync(p));
}

// Lee telemetry_events con el mismo código y la misma base de datos que la API.
const STORED_ROWS_SCRIPT = `
import json, sys, uuid
from datetime import datetime, timezone
from sqlalchemy import and_, or_, select
from sqlmodel import Session
from services.database import engine
from services.telemetry_models import TelemetryEventRecord as T

q = json.load(open(sys.argv[1], encoding="utf-8"))
since = datetime.fromisoformat(q["since"])

def iso(d):
    d = d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")

with Session(engine) as s:
    rows = s.exec(select(T).where(or_(T.id.in_([uuid.UUID(i) for i in q["ids"]]), and_(T.source == "api", T.timestamp >= since)))).scalars().all()
    print(json.dumps([
        {"id": str(r.id), "event_type": r.event_type, "timestamp": iso(r.timestamp), "session_id": r.session_id,
         "user_id": r.user_id, "source": r.source, "tags": r.tags, "created_at": iso(r.created_at)}
        for r in rows
    ]))
`;

/** Filas de telemetry_events de esta ejecución: las de los eventIds dados y las que emitió la API desde `since`. */
function storedRows(repoRoot, tempDir, databaseUrl, { ids, since }) {
  const file = path.join(tempDir, "ids.json");
  fs.writeFileSync(file, JSON.stringify({ ids, since }));
  const env = { ...process.env, TINYDB_PATH: path.join(tempDir, "db.json") };
  if (databaseUrl === null) delete env.DATABASE_URL;
  else env.DATABASE_URL = databaseUrl;
  const result = spawnSync(python(repoRoot), ["-c", STORED_ROWS_SCRIPT, file], { cwd: repoRoot, encoding: "utf8", env });
  try {
    return JSON.parse(result.stdout.trim().split("\n").at(-1));
  } catch {
    return { error: (result.stderr || result.stdout).slice(-800) };
  }
}

/** Las tags que debe tener la fila de un evento: sus properties + los 3 campos del envelope sin columna. */
function expectedTags(event) {
  return { ...event.properties, environment: event.environment, schema_version: event.schemaVersion, request_id: event.requestId };
}

// JSONB no conserva el orden de las claves: se comparan ordenadas, a cualquier profundidad.
const canonical = (v) => (Array.isArray(v) ? v.map(canonical) : v && typeof v === "object" ? Object.fromEntries(Object.keys(v).sort().map((k) => [k, canonical(v[k])])) : v);
const sameTags = (a, b) => Boolean(a && b) && JSON.stringify(canonical(a)) === JSON.stringify(canonical(b));

/** Valida los eventos con services.telemetry (el mismo código que usa el stub). */
function schemaViolations(repoRoot, tempDir, events) {
  const python = process.env.PYTHON || [path.join(repoRoot, ".venv", "Scripts", "python.exe"), path.join(repoRoot, ".venv", "bin", "python")].find((p) => fs.existsSync(p));
  const file = path.join(tempDir, "events.json");
  fs.writeFileSync(file, JSON.stringify(events));
  const script =
    "import json,sys\nfrom services import telemetry\n" +
    "events=json.load(open(sys.argv[1],encoding='utf-8'))\n" +
    "bad={e['event_type']:telemetry.schema_violations(e) for e in events if telemetry.schema_violations(e)}\n" +
    "def envelope_ok(e):\n try:\n  telemetry.TelemetryEvent.model_validate(e)\n  return True\n except Exception:\n  return False\n" +
    "envelope=[e['event_type'] for e in events if not envelope_ok(e)]\n" +
    "print(json.dumps({'violations':bad,'envelope':envelope}))";
  const result = spawnSync(python, ["-c", script, file], { cwd: repoRoot, encoding: "utf8", env: { ...process.env, DATABASE_URL: "sqlite://" } });
  try {
    return JSON.parse(result.stdout.trim().split("\n").at(-1));
  } catch {
    return { error: (result.stderr || result.stdout).slice(-600) };
  }
}

export async function run({ repoRoot }) {
  const rec = new Recorder("telemetry");
  const apiTemp = makeTempDir("telemetry-api");
  const databaseUrl = ON_SUPABASE ? null : disposableDatabaseUrl(apiTemp);
  const startedAt = new Date().toISOString();
  const browser = await launchChrome();
  let stack = null;
  let cleanup = {};

  try {
    stack = await startStack(repoRoot, apiTemp, { databaseUrl });
    const { api, app: web } = stack;
    const data = await seed(api.origin);
    const policy = ({ url }) => url.hostname === "127.0.0.1";
    const page = await openPage(browser, { policy });
    const run = (expression) => page.eval(`(()=>{${PAGE_HELPERS}return ${expression}})()`);
    const settle = (expression, timeout = 30000) => waitFor(() => run(expression), timeout);

    // ---------------------------------------------------------- login fallido y login
    await page.goto(`${web.origin}/login`, 120000);
    await settle(`!!q('form input[name=email]')`);
    await page.eval(setValue("input[name=email]", EMAIL, "input"));
    await page.eval(setValue("input[name=password]", WRONG_PASSWORD, "input"));
    await settle(`!q('form button[type=submit]').disabled`);
    await page.eval(submit("form"));
    await settle(`/incorrect/i.test(document.body.textContent)`, 20000);
    await page.eval(setValue("input[name=password]", PASSWORD, "input"));
    await page.eval(submit("form"));
    await settle(`location.pathname==='/'`, 60000);

    // ---------------------------------------------------------- entrada correcta
    await page.goto(`${web.origin}/inventory/orders/inbound?sku_id=${data.sku.id}`, 120000);
    await settle(`q('#sku_idInput')?.value==='${data.sku.id}'`, 60000);
    await page.eval(setValue("#quantityInput", "5", "input"));
    await page.eval(setValue("#referenceInput", REFERENCE, "input"));
    await page.eval(submit("#entryForm"));
    await settle(`q('#formAlert').dataset.type==='success'`);

    // ---------------------------------------------------------- salida rechazada y salida correcta
    await page.goto(`${web.origin}/inventory/orders/outbound?sku_id=${data.sku.id}`, 120000);
    await settle(`q('#availableStock')?.dataset.units==='25'`, 60000);
    await page.eval(setValue("#trackingInput", "1Z999AA10123456784", "input"));
    // Más de lo que hay, saltándose el aviso del cliente: la API responde 400.
    await page.eval(setValue("#quantityInput", "40", "input"));
    await page.eval(submit("#exitForm"));
    await settle(`q('#formAlert').dataset.type==='error'`);
    await page.eval(setValue("#quantityInput", "3", "input"));
    await page.eval(submit("#exitForm"));
    await settle(`q('#formAlert').dataset.type==='success'`);

    // ---------------------------------------------------------- formulario abandonado y error de JS
    await page.eval(setValue("#sku_idInput", String(data.sku.id)));
    await page.eval(setValue("#quantityInput", "2", "input"));
    await settle(`q('#quantityInput').value==='2'`);
    // Navegación interna: el formulario se desmonta sucio.
    await page.eval(`(()=>{document.querySelector('nav[aria-label=Inventario] a[href="/inventory/products"]').click();return true})()`);
    await settle(`location.pathname==='/inventory/products'`);
    await page.eval(`setTimeout(()=>{throw new TypeError('Fallo de prueba con datos de Ana García')},0);true`);
    // Evento técnico que emite la API: intento de fijar el stock con PUT (405 → direct_stock_edit_rejected).
    const directEditRequestId = crypto.randomUUID();
    const directEdit = await fetch(`${api.origin}/inventory/products/${data.sku.id}`, {
      method: "PUT",
      headers: { Authorization: `Bearer ${data.token}`, "Content-Type": "application/json", "X-Request-Id": directEditRequestId },
      body: JSON.stringify({ current_stock: 999 }),
    });

    // ---------------------------------------------------------- lotes por fetch (10 s)
    const telemetryRequests = () => page.state.requests.filter((r) => r.path === "/telemetry/events" && r.method === "POST");
    // El temporizador del TelemetryService envía lo pendiente a los 10 s.
    await new Promise((resolve) => setTimeout(resolve, 11000));

    // ---------------------------------------------------------- cerrar: sendBeacon
    await page.goto("about:blank", 20000);
    await waitFor(() => telemetryRequests().some((r) => r.type === "Ping"), 10000);
    await new Promise((resolve) => setTimeout(resolve, 1500));

    // ---------------------------------------------------------- comprobaciones de red
    const requests = telemetryRequests();
    const batches = requests.map((r) => {
      try {
        return JSON.parse(r.postData).events;
      } catch {
        return null;
      }
    });
    const events = batches.flat().filter(Boolean);
    const types = [...new Set(events.map((e) => e.event_type))];
    const responses = page.state.responses.filter((r) => r.path === "/telemetry/events" && r.type !== "Preflight");
    const log = api.output.join("");

    rec.check("TEL-01", "the backoffice sends telemetry in batches {events:[...]}, not one request per event",
      batches.every(Array.isArray) && requests.length >= 2 && requests.length < events.length, { requests: requests.length, events: events.length });
    // DevTools no siempre recibe la respuesta de un sendBeacon (la página ya se ha descargado): el
    // estado de cada POST se lee también del log de la API, que registra todas.
    // Log de accesos de uvicorn: una línea por petición recibida.
    const served = [...log.matchAll(/"POST \/telemetry\/events HTTP\/1\.1" (\d{3})/g)].map((m) => Number(m[1]));
    rec.check("TEL-02", "every POST /telemetry/events answered 200 (DevTools responses and the API log)",
      served.length === requests.length && served.every((status) => status === 200) && responses.every((r) => r.status === 200),
      { requests: requests.length, served, devtools: responses.map((r) => [r.type, r.status]) });
    rec.check("TEL-03", "leaving a page flushes the queue with navigator.sendBeacon (type Ping, text/plain)",
      requests.some((r) => r.type === "Ping" && /text\/plain/i.test(r.headers["Content-Type"] || r.headers["content-type"] || "")), requests.map((r) => r.type));
    rec.check("TEL-04", `the flow produced ${EXPECTED_TYPES.join(", ")}`,
      EXPECTED_TYPES.every((t) => types.includes(t)), { missing: EXPECTED_TYPES.filter((t) => !types.includes(t)), types });
    rec.check("TEL-05", "the API logged each batch (received/stored/rejected, no rejections) and its event types",
      /telemetry batch received=\d+ stored=\d+ rejected=0/.test(log) && !/telemetry batch received=\d+ stored=\d+ rejected=[1-9]/.test(log) &&
      /telemetry stored=\d+ of=\d+ source=backoffice_web event_types=/.test(log) && EXPECTED_TYPES.every((t) => log.includes(t)));

    const validation = schemaViolations(repoRoot, apiTemp, events);
    rec.check("TEL-06", "every event validates against its schema in event-schemas.json (envelope + allowlist)",
      validation.violations && Object.keys(validation.violations).length === 0 && validation.envelope.length === 0, validation);

    const serialized = JSON.stringify(events);
    rec.check("TEL-07", "no PII: neither the email, the passwords, the client reference nor the error message travel in any event",
      ![EMAIL, PASSWORD, WRONG_PASSWORD, REFERENCE, "Ana García"].some((value) => serialized.includes(value)));

    const loginFailed = events.find((e) => e.event_type === "login_failed");
    rec.check("TEL-08", "login_failed carries only failure_reason = invalid_credentials and userId null",
      loginFailed && JSON.stringify(loginFailed.properties) === JSON.stringify({ failure_reason: "invalid_credentials" }) && loginFailed.userId === null, loginFailed);

    const inbound = events.find((e) => e.event_type === "inbound_order_created");
    const inboundCall = page.state.requests.find((r) => r.path === "/inventory/orders/inbound" && r.method === "POST");
    const callRequestId = inboundCall && (inboundCall.headers["X-Request-Id"] || inboundCall.headers["x-request-id"]);
    rec.check("TEL-09", "inbound_order_created has the X-Request-Id of its API call and the stock left after it",
      inbound && callRequestId && inbound.requestId === callRequestId && inbound.properties.stock_after === 25 && inbound.properties.client_id === "soundwave_electronics",
      { event: inbound?.properties, requestId: inbound?.requestId, callRequestId });

    const rejected = events.find((e) => e.event_type === "outbound_order_rejected");
    rec.check("TEL-10", "outbound_order_rejected carries the requested and available quantities",
      rejected && rejected.properties.quantity === 40 && rejected.properties.available_quantity === 25, rejected?.properties);

    // El login empieza una sesión de telemetría nueva: lo de antes (pantalla de login) va en otra.
    const authenticated = events.filter((e) => e.userId !== null);
    const sessions = new Set(authenticated.map((e) => e.sessionId));
    const userIds = new Set(authenticated.map((e) => e.userId));
    rec.check("TEL-11", "after login every event shares one new sessionId and the pseudonymous userId (never an email)",
      sessions.size === 1 && userIds.size === 1 && /^[0-9a-f-]{36}$/.test([...userIds][0]) && !sessions.has(loginFailed?.sessionId),
      { sessions: [...sessions], userIds: [...userIds], beforeLogin: loginFailed?.sessionId });

    // ---------------------------------------------------------- almacenamiento (hito 16)
    // Lote mixto enviado a mano, como haría curl: 2 válidos, 1 envelope roto y 1 fuera de su allowlist.
    const template = events.find((e) => e.event_type === "page_viewed");
    const validOnes = [0, 1].map(() => ({ ...template, eventId: crypto.randomUUID(), requestId: crypto.randomUUID() }));
    const brokenEnvelope = { ...template, eventId: "no-es-un-uuid" };
    const leaky = { ...template, eventId: crypto.randomUUID(), properties: { ...template.properties, email: EMAIL } };
    const mixedResponse = await fetch(`${api.origin}/telemetry/events`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ events: [validOnes[0], brokenEnvelope, leaky, validOnes[1]] }),
    });
    const mixed = await mixedResponse.json().catch(() => null);
    rec.check("TEL-13", "a manual mixed batch answers 200 {received:4, stored:2, rejected:2}",
      mixedResponse.status === 200 && JSON.stringify(mixed) === JSON.stringify({ received: 4, stored: 2, rejected: 2 }), { status: mixedResponse.status, body: mixed });

    const sentIds = [...new Set(events.map((e) => e.eventId))];
    const stored = storedRows(repoRoot, apiTemp, databaseUrl, { ids: [...sentIds, ...validOnes.map((e) => e.eventId), leaky.eventId], since: startedAt });
    const rowsOk = Array.isArray(stored);
    const byId = new Map(rowsOk ? stored.map((r) => [r.id, r]) : []);
    rec.check("TEL-14", `every event the backoffice sent is in telemetry_events exactly once (${ON_SUPABASE ? "Supabase" : "disposable SQLite"})`,
      rowsOk && sentIds.every((id) => byId.has(id)) && stored.length === new Set(stored.map((r) => r.id)).size,
      rowsOk ? { sent: sentIds.length, missing: sentIds.filter((id) => !byId.has(id)).length } : stored);

    const mismatches = rowsOk ? events.filter((e) => {
      const row = byId.get(e.eventId);
      return !row || row.event_type !== e.event_type || row.timestamp !== e.timestamp || row.source !== "backoffice_web" ||
        row.session_id !== e.sessionId || row.user_id !== e.userId || !sameTags(row.tags, expectedTags(e));
    }).map((e) => e.event_type) : ["(no rows)"];
    rec.check("TEL-15", "each row has the event_type, timestamp, session/user and tags (properties + environment, schema_version, request_id) of its event",
      mismatches.length === 0, { mismatches });

    const rowOf = (type) => (rowsOk ? events.filter((e) => e.event_type === type).map((e) => byId.get(e.eventId)).find(Boolean) : undefined);
    const inboundRow = rowOf("inbound_order_created");
    const outboundRow = rowOf("outbound_order_created");
    const briefing = (row) => row && row.tags.warehouse === "los_angeles" && row.tags.country === "US" && row.tags.client_id === "soundwave_electronics" &&
      row.tags.product_id === SKU_CODE && row.tags.product_category === "electronics" && Number.isInteger(row.tags.quantity);
    rec.check("TEL-16", "business rows (inbound/outbound) keep the BRIEFING dimensions in tags: warehouse, country, client_id, product_id, product_category, quantity",
      briefing(inboundRow) && briefing(outboundRow) && inboundRow.tags.quantity === 5 && outboundRow.tags.quantity === 3,
      { inbound: inboundRow?.tags, outbound: outboundRow?.tags });

    const technical = ["login_failed", "frontend_error_captured", "page_load_recorded"].map((type) => [type, rowOf(type)]);
    const serverRow = rowsOk && stored.find((r) => r.source === "api" && r.event_type === "direct_stock_edit_rejected" && r.tags.request_id === directEditRequestId);
    rec.check("TEL-17", "technical events are stored too: login_failed, frontend_error_captured, page_load_recorded and the API's direct_stock_edit_rejected",
      technical.every(([, row]) => row) && directEdit.status === 405 && serverRow && serverRow.tags.http_method === "PUT" && serverRow.tags.rejection_type === "method_not_allowed",
      { missing: technical.filter(([, row]) => !row).map(([type]) => type), directEditStatus: directEdit.status, server: serverRow?.tags });

    rec.check("TEL-18", "from the mixed batch only the 2 valid events were stored (neither the broken envelope nor the one with an email)",
      rowsOk && validOnes.every((e) => byId.has(e.eventId)) && !byId.has(leaky.eventId) && !JSON.stringify(stored).includes(EMAIL),
      { valid: validOnes.map((e) => byId.has(e.eventId)), leakyStored: byId.has(leaky.eventId) });

    rec.check("TEL-12", "the telemetry endpoint comes from NEXT_PUBLIC_TELEMETRY_ENDPOINT (the API of this test, 127.0.0.1)",
      requests.every((r) => r.host === new URL(api.origin).host));
    rec.check("TEL-NET", "no request left 127.0.0.1; nothing blocked",
      page.state.blocked.length === 0 && page.state.requests.every((r) => r.host.startsWith("127.0.0.1")), page.state.blocked);
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
  rec.check("TEL-CLEAN", `uvicorn and next dev stopped; Chrome profile and the disposable TinyDB${ON_SUPABASE ? "" : "/SQLite"} removed`,
    cleanup.profileRemoved && cleanup.apiTempRemoved && (stack ? cleanup.apiStopped && cleanup.nextStopped : true), cleanup);
  return rec;
}
