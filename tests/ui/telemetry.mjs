// Telemetría del backoffice (hito 15) en un navegador real: lo mismo que se ve en la pestaña Network
// de DevTools.
//
// Arranca la API (con el stub POST /telemetry/events) y el backoffice con
// NEXT_PUBLIC_TELEMETRY_ENDPOINT apuntando a ella, recorre un flujo de inventario (login fallido,
// login, entrada, salida rechazada, salida correcta, formulario abandonado, error de JavaScript,
// cerrar la pestaña) y comprueba en la red:
//
//  * que los eventos salen en lotes y el stub responde 200 a todos (fetch y sendBeacon);
//  * que cada evento cumple su esquema de event-schemas.json (validado con la API de Python);
//  * que ningún evento lleva el email, la contraseña ni la referencia del cliente;
//  * que el evento de un alta lleva el mismo X-Request-Id que la llamada a la API.

import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { PAGE_HELPERS, Recorder, killTree, launchChrome, makeTempDir, openPage, removeDir, waitExit, waitFor } from "./lib/harness.mjs";
import { apiCall, createUser, setValue, startStack, submit } from "./lib/backoffice-app.mjs";

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
    token, body: { name: "Auriculares inalámbricos Pro", sku: "TEC-EAR-001", client_name: "SoundWave Electronics", category: "electronics", warehouse: "LA" },
  });
  await apiCall(origin, "POST", "/inventory/orders/inbound", { token, body: { sku_id: sku.id, quantity: 20, warehouse: "LA", reference: "PO-2024-0112" } });
  return { sku };
}

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
  const browser = await launchChrome();
  let stack = null;
  let cleanup = {};

  try {
    stack = await startStack(repoRoot, apiTemp);
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
    rec.check("TEL-05", "the API stub logged each batch with its count and event types",
      /telemetry batch received=\d+ valid=\d+ source=backoffice_web event_types=/.test(log) && EXPECTED_TYPES.every((t) => log.includes(t)));

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
  rec.check("TEL-CLEAN", "uvicorn and next dev stopped; Chrome profile and the disposable TinyDB/SQLite removed",
    cleanup.profileRemoved && cleanup.apiTempRemoved && (stack ? cleanup.apiStopped && cleanup.nextStopped : true), cleanup);
  return rec;
}
