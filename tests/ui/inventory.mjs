// Inventario del backoffice (CONTEXT-9) en un navegador real.
//
// Arranca la API (uvicorn) con TinyDB y un SQLite desechables — nunca el Supabase del .env — y el
// backoffice Next.js (uis/backoffice), siembra SKUs y movimientos por HTTP y recorre las cuatro
// vistas: guard de sesión, stock con indicadores, recepción, salida con stock reactivo y 400
// inline, e historial de solo lectura.

import fs from "node:fs";
import path from "node:path";
import { PAGE_HELPERS, Recorder, killTree, launchChrome, makeTempDir, openPage, removeDir, waitExit, waitFor } from "./lib/harness.mjs";
import { apiCall, click, createUser, setValue, signIn, startStack, submit } from "./lib/backoffice-app.mjs";

const EMAIL = "operaciones-ui@trackflow.com";
const PASSWORD = "inventario-ui-1234";

const PAGES = {
  products: "/inventory/products",
  inbound: "/inventory/orders/inbound",
  outbound: "/inventory/orders/outbound",
  orders: "/inventory/orders",
};

// SKUs con un nivel de stock de cada tipo (umbral de stock bajo: 50 unidades).
async function seed(origin) {
  const { token, userId } = await createUser(origin, EMAIL, PASSWORD);
  const sku = (body) => apiCall(origin, "POST", "/inventory/products", { token, body });
  const skus = {
    sneaker: await sku({ name: "Zapatilla blanca clásica - Talla 42", sku: "CLT-SNK-W-42", client_name: "PureStep Footwear", category: "fashion", warehouse: "LA" }),
    earbuds: await sku({ name: "Auriculares inalámbricos Pro", sku: "TEC-EAR-001", client_name: "SoundWave Electronics", category: "electronics", warehouse: "LA" }),
    serum: await sku({ name: "Sérum facial hidratante 30ml", sku: "CSM-SRM-030", client_name: "GlowLab Cosmetics", category: "cosmetics", warehouse: "ZGZ" }),
    charger: await sku({ name: "Cargador rápido USB-C 65W", sku: "TEC-CHG-065", client_name: "SoundWave Electronics", category: "electronics", warehouse: "ZGZ" }),
  };
  const entry = (s, quantity, warehouse, reference) =>
    apiCall(origin, "POST", "/inventory/orders/inbound", { token, body: { sku_id: s.id, quantity, warehouse, reference } });
  await entry(skus.sneaker, 120, "LA", "PO-2024-0098");
  await entry(skus.earbuds, 20, "LA", "PO-2024-0112");
  await entry(skus.earbuds, 15, "ZGZ", "GR-ZGZ-0064");
  await entry(skus.charger, 60, "ZGZ", "GR-ZGZ-0061");
  await apiCall(origin, "POST", "/inventory/orders/outbound", {
    token, body: { sku_id: skus.sneaker.id, quantity: 30, exit_type: "dispatch", tracking_number: "1Z999AA10123456784", warehouse: "LA" },
  });
  // sneaker 90 (OK) · earbuds 20 en LA (bajo) + 15 en ZGZ · serum 0 (sin stock) · charger 60 (OK)
  return { token, userId, skus, seededOrders: 5 };
}

function walk(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => (e.isDirectory() ? walk(path.join(dir, e.name)) : [path.join(dir, e.name)]));
}

export async function run({ repoRoot }) {
  const rec = new Recorder("inventory");
  const apiTemp = makeTempDir("inventory-api");
  const browser = await launchChrome();
  let stack = null;
  let cleanup = {};

  try {
    // ---------------------------------------------------------- integración: sin fetch en las páginas
    const app = path.join(repoRoot, "uis", "backoffice", "app");
    const pageFiles = [...walk(path.join(app, "(protected)", "inventory")), path.join(app, "ui", "inventory-ui.tsx")].filter((f) => /\.tsx?$/.test(f));
    const withFetch = pageFiles.filter((file) => /\bfetch\s*\(/.test(fs.readFileSync(file, "utf8"))).map((f) => path.relative(app, f));
    rec.check("INV-00", "no inventory page or UI component calls fetch directly: every request goes through lib/inventory.ts",
      pageFiles.length >= 9 && withFetch.length === 0, { files: pageFiles.length, withFetch });
    const apiModule = fs.readFileSync(path.join(app, "lib", "inventory.ts"), "utf8");
    rec.check("INV-00b", "lib/inventory.ts sends every request through backofficeFetch (Bearer token)",
      /backofficeFetch\(/.test(apiModule) && !/\bfetch\s*\(/.test(apiModule.replace(/backofficeFetch\(/g, "")));

    stack = await startStack(repoRoot, apiTemp);
    const { api, app: web } = stack;
    const data = await seed(api.origin);
    const policy = ({ url }) => url.hostname === "127.0.0.1";
    const page = await openPage(browser, { policy });
    const run = (expression) => page.eval(`(()=>{${PAGE_HELPERS}return ${expression}})()`);
    const settle = (expression, timeout = 30000) => waitFor(() => run(expression), timeout);
    const apiResponses = (pathName) => page.state.responses.filter((r) => r.path === pathName && r.type !== "Preflight");

    // ---------------------------------------------------------- guard de sesión
    for (const [key, pagePath] of Object.entries(PAGES)) {
      await page.goto(web.origin + pagePath, 120000);
      const landed = await settle(`location.pathname==='/login' && location.search`, 90000);
      const next = landed ? new URLSearchParams(landed).get("next") : null;
      rec.check(`INV-AUTH-${key}`, `without a session ${pagePath} redirects to /login?next=${pagePath}`, next === pagePath, { landed, next });
    }

    // Login real desde el formulario: vuelve a la página pedida.
    await page.goto(`${web.origin}/login?next=${encodeURIComponent(PAGES.outbound)}`, 60000);
    await settle(`!!document.querySelector('form input[name=email]')`);
    await page.eval(setValue("input[name=email]", EMAIL, "input"));
    await page.eval(setValue("input[name=password]", PASSWORD, "input"));
    await settle(`!q('form button[type=submit]').disabled`);
    await page.eval(submit("form"));
    const backTo = await settle(`location.pathname==='${PAGES.outbound}' && location.pathname`, 60000);
    rec.check("INV-AUTH-login", "logging in from /login?next=/inventory/orders/outbound returns to that page", !!backTo, { backTo });

    // /inventory redirige a la vista de stock.
    await page.goto(`${web.origin}/inventory`, 60000);
    const redirected = await settle(`location.pathname==='/inventory/products' && document.querySelectorAll('#skuTableBody tr').length`, 60000);
    rec.check("INV-ROUTE", "/inventory redirects to /inventory/products and renders", redirected === 4, { rows: redirected });

    // ---------------------------------------------------------- stock por SKU
    await page.goto(web.origin + PAGES.products, 60000);
    await settle(`document.querySelectorAll('#skuTableBody tr').length===4`);
    const products = await run(`({
      rows: qa('#skuTableBody tr').map(r=>({sku:r.cells[0].textContent.trim(), level:r.dataset.level, stock:r.cells[5].querySelector('[data-level]')?.textContent.trim(),
        extra: r.cells[5].querySelector('p')?.textContent.trim()||null, links: qa('a').filter(a=>r.contains(a)).map(a=>a.getAttribute('href')) })),
      headers: qa('thead th').map(th=>th.textContent.trim()),
      total: txt('#totalCount'), low: txt('#lowCount'), out: txt('#outCount'),
      alertVisible: vis('#listAlert').visible })`);
    const bySku = Object.fromEntries(products.rows.map((r) => [r.sku, r]));
    rec.check("INV-P-01", "products page lists every SKU from GET /inventory/products with CONTEXT-9 columns",
      products.rows.length === 4 && JSON.stringify(products.headers.slice(0, 6)) === JSON.stringify(["SKU", "Nombre", "Marca cliente", "Categoría", "Almacén", "Stock actual"]), products.headers);
    rec.check("INV-P-02", "current_stock shown per SKU (own warehouse, never summed): 90 · 20 · 0 · 60",
      bySku["CLT-SNK-W-42"]?.stock?.includes("90 unidades") && bySku["TEC-EAR-001"]?.stock?.includes("20 unidades") &&
        bySku["CSM-SRM-030"]?.stock?.includes("0 unidades") && bySku["TEC-CHG-065"]?.stock?.includes("60 unidades"), bySku);
    rec.check("INV-P-03", "stock level indicators: OK (≥50), low (1–49), out (0)",
      bySku["CLT-SNK-W-42"]?.level === "ok" && bySku["TEC-EAR-001"]?.level === "low" && bySku["CSM-SRM-030"]?.level === "out" && bySku["TEC-CHG-065"]?.level === "ok", bySku);
    rec.check("INV-P-04", "stock in the other warehouse is shown separately (TEC-EAR-001: 15 in Zaragoza)",
      bySku["TEC-EAR-001"]?.extra === "En Zaragoza: 15 unidades", bySku["TEC-EAR-001"]);
    rec.check("INV-P-05", "summary counts: 4 SKUs, 1 low, 1 out of stock", products.total === "4" && products.low === "1" && products.out === "1", products);
    rec.check("INV-P-06", "each row links to register an entry and an exit for that SKU",
      products.rows.every((r) => r.links.length === 2 && r.links[0].startsWith("/inventory/orders/inbound?sku_id=") && r.links[1].startsWith("/inventory/orders/outbound?sku_id=")), products.rows.map((r) => r.links));
    await page.eval(setValue("#levelFilter", "out"));
    const outOnly = await settle(`(()=>{const v=qa('#skuTableBody tr').map(r=>r.cells[0].textContent.trim());return v.length===1?v:null})()`, 5000);
    rec.check("INV-P-07", "level filter 'Solo sin stock' shows only CSM-SRM-030", JSON.stringify(outOnly) === JSON.stringify(["CSM-SRM-030"]), outOnly);

    // ---------------------------------------------------------- recepción de mercancía
    await page.goto(`${web.origin}${PAGES.inbound}?sku_id=${data.skus.serum.id}`, 60000);
    await settle(`document.querySelector('#sku_idInput')?.value==='${data.skus.serum.id}'`);
    const preselected = await run(`({sku: q('#sku_idInput').value, warehouse: q('#warehouseInput').value, hint: txt('#skuHint'),
      optionText: q('#sku_idInput').selectedOptions[0].textContent})`);
    rec.check("INV-IN-01", "SKU select lists SKUs by name and the row link preselects the SKU and its warehouse",
      preselected.warehouse === "ZGZ" && preselected.optionText.startsWith("Sérum facial hidratante 30ml") && preselected.hint.includes("0 unidades"), preselected);

    const before = apiResponses("/inventory/orders/inbound").length;
    await page.eval(setValue("#sku_idInput", ""));
    await page.eval(setValue("#warehouseInput", ""));
    await page.eval(submit("#entryForm"));
    const emptyErrors = await settle(`(()=>{const e=qa('[data-error-for]').filter(p=>!p.hidden).map(p=>p.dataset.errorFor);return e.length?{errors:e, alert: txt('#formAlert'), alertVisible: vis('#formAlert').visible}:null})()`, 5000);
    rec.check("INV-IN-02", "empty submit shows field errors and sends nothing",
      !!emptyErrors && ["sku_id", "warehouse", "quantity", "reference"].every((f) => emptyErrors.errors.includes(f)) && emptyErrors.alertVisible &&
        apiResponses("/inventory/orders/inbound").length === before, emptyErrors);

    await page.eval(setValue("#sku_idInput", data.skus.serum.id));
    await page.eval(setValue("#quantityInput", "7", "input"));
    await page.eval(setValue("#referenceInput", "PO-2024-0131", "input"));
    await page.eval(submit("#entryForm"));
    const success = await settle(`q('#formAlert').dataset.type==='success' && ({text: txt('#formAlert'), sku: q('#sku_idInput').value, qty: q('#quantityInput').value, ref: q('#referenceInput').value})`);
    rec.check("INV-IN-03", "valid entry: confirmation with the new stock, and the form is cleared",
      success && success.text.includes("Entrada registrada") && success.text.includes("Stock actual en Zaragoza: 7 unidades") && !success.sku && !success.qty && !success.ref, success);

    await page.eval(setValue("#sku_idInput", data.skus.serum.id));
    await page.eval(setValue("#quantityInput", "2147483648", "input"));
    await page.eval(setValue("#referenceInput", "PO-TOO-BIG", "input"));
    await page.eval(submit("#entryForm"));
    const rejected = await settle(`q('#formAlert').dataset.type==='error' && ({alert: txt('#formAlert'), field: txt('[data-error-for="quantity"]'), visible: vis('[data-error-for="quantity"]').visible})`);
    rec.check("INV-IN-04", "an API rejection (422) is shown on screen: alert + message next to the field",
      rejected && rejected.visible && rejected.field === "La cantidad es demasiado grande." && rejected.alert.startsWith("No se ha registrado la entrada"), rejected);

    // ---------------------------------------------------------- salida de stock
    await page.goto(web.origin + PAGES.outbound, 60000);
    await settle(`q('#sku_idInput')?.options.length>1 && !q('#sku_idInput').disabled`);
    const skuFetches = () => page.state.responses.filter((r) => /^\/inventory\/products\/\d+$/.test(r.path) && r.type !== "Preflight").length;
    const fetchesBefore = skuFetches();
    await page.eval(setValue("#sku_idInput", data.skus.earbuds.id));
    const earbudsLa = await settle(`q('#availableStock')?.dataset.units`);
    rec.check("INV-OUT-01", "selecting a SKU fetches its current stock (GET /inventory/products/{id}) and shows it before submitting",
      earbudsLa === "20" && skuFetches() === fetchesBefore + 1 && (await run(`txt('#stockPanel')`)).includes("Disponible en Los Ángeles"), { earbudsLa, fetches: skuFetches() - fetchesBefore });
    await page.eval(setValue("#warehouseInput", "ZGZ"));
    const earbudsZgz = await settle(`q('#availableStock')?.dataset.units==='15' && txt('#stockPanel')`);
    rec.check("INV-OUT-02", "changing the warehouse updates the available stock reactively (15 in Zaragoza)", !!earbudsZgz, { earbudsZgz });
    await page.eval(setValue("#sku_idInput", data.skus.sneaker.id));
    const sneaker = await settle(`q('#availableStock')?.dataset.units==='90' && q('#warehouseInput').value`);
    rec.check("INV-OUT-03", "changing the SKU updates the stock and resets the warehouse to the SKU's (90 in LA)", sneaker === "LA", { sneaker });
    const nextToQuantity = await run(`({text: txt('#quantityAvailable'), visible: vis('#quantityAvailable').visible})`);
    rec.check("INV-OUT-03b", "the available stock is also shown right under the quantity field (visible on mobile too)",
      nextToQuantity.visible && nextToQuantity.text === "Disponible en Los Ángeles: 90 unidades", nextToQuantity);

    await page.eval(setValue("#quantityInput", "100", "input"));
    const warning = await settle(`vis('#quantityWarning').visible && ({visible: true, text: txt('#quantityWarning')})`, 5000);
    rec.check("INV-OUT-04", "a quantity above the shown stock triggers a client-side warning before submitting",
      warning && warning.text.includes("100 unidades") && warning.text.includes("90 unidades"), warning);
    await page.eval(setValue("#quantityInput", "90", "input"));
    rec.check("INV-OUT-05", "the warning disappears when the quantity fits the stock", !!(await settle(`!vis('#quantityWarning').visible`, 5000)));

    const exitsBefore = apiResponses("/inventory/orders/outbound").length;
    await page.eval(setValue("#quantityInput", "5", "input"));
    await page.eval(setValue("#trackingInput", "", "input"));
    await page.eval(submit("#exitForm"));
    const noTracking = await settle(`vis('[data-error-for="tracking_number"]').visible && ({field: txt('[data-error-for="tracking_number"]'), visible: true})`, 5000);
    rec.check("INV-OUT-06", "a dispatch without tracking number is stopped in the form (nothing sent)",
      noTracking && noTracking.field.includes("obligatorio") && apiResponses("/inventory/orders/outbound").length === exitsBefore, noTracking);

    await page.eval(click('input[name="exit_type"][value="loss"]'));
    rec.check("INV-OUT-07", "choosing 'Pérdida' hides the tracking number field", !!(await settle(`!vis('#trackingField').visible`, 5000)));
    await page.eval(click('input[name="exit_type"][value="dispatch"]'));
    await settle(`vis('#trackingField').visible`, 5000);

    // 400 de la API: stock insuficiente. Se fuerza con una cantidad mayor que el stock real.
    await page.eval(setValue("#quantityInput", "100", "input"));
    await page.eval(setValue("#trackingInput", "1Z999AA10123456791", "input"));
    await page.eval(submit("#exitForm"));
    const insufficient = await settle(`!vis('[data-error-for="quantity"]').visible ? null : ({field: txt('[data-error-for="quantity"]'), alert: txt('#formAlert'),
      focused: document.activeElement?.id, invalid: q('#quantityInput').getAttribute('aria-invalid')})`);
    await settle(`document.activeElement?.id==='quantityInput'`, 3000);
    const focused = await run(`document.activeElement?.id`);
    const response400 = apiResponses("/inventory/orders/outbound").at(-1);
    rec.check("INV-OUT-08", "API 400 (insufficient stock) is shown inline next to the quantity field in readable Spanish",
      response400?.status === 400 && insufficient &&
        insufficient.field === "Stock insuficiente para CLT-SNK-W-42 en Los Ángeles: hay 90 unidades disponibles y has pedido 100. No se ha registrado la salida." &&
        focused === "quantityInput" && insufficient.invalid === "true", { status: response400?.status, insufficient, focused });
    await settle(`q('#stockPanel').dataset.status==='ready'`, 10000);
    const noDouble = !(await run(`vis('#quantityWarning').visible`));
    await page.eval(setValue("#quantityInput", "95", "input"));
    const cleared = await settle(`!vis('[data-error-for="quantity"]').visible && vis('#quantityWarning').visible`, 5000);
    rec.check("INV-OUT-08b", "after the API 400 the client warning is not shown twice; editing the quantity clears the API error",
      noDouble && !!cleared, { noDouble, cleared: !!cleared });

    await page.eval(setValue("#quantityInput", "10", "input"));
    await page.eval(submit("#exitForm"));
    const exitOk = await settle(`q('#formAlert').dataset.type==='success' && ({text: txt('#formAlert'), sku: q('#sku_idInput').value, panel: txt('#stockPanel')})`);
    rec.check("INV-OUT-09", "valid dispatch: confirmation with the remaining stock, form and stock panel reset",
      exitOk && exitOk.text.includes("Salida registrada") && exitOk.text.includes("Quedan 80 unidades en Los Ángeles") && !exitOk.sku &&
        exitOk.panel.startsWith("Selecciona un SKU"), exitOk);

    // ---------------------------------------------------------- movimientos de stock
    await page.goto(web.origin + PAGES.orders, 60000);
    const expectedOrders = data.seededOrders + 2;
    await settle(`document.querySelectorAll('#ordersTableBody tr').length===${expectedOrders}`);
    const orders = await run(`({
      rows: qa('#ordersTableBody tr').map(r=>({type:r.dataset.orderType, badge:r.cells[1].querySelector('span').textContent.trim(),
        sku:r.cells[2].textContent, qty:r.cells[3].textContent.trim(), date:r.cells[0].textContent.trim(), user:r.cells[6].textContent})),
      headers: qa('thead th').map(th=>th.textContent.trim()),
      buttons: qa('main button').map(b=>b.id), forms: qa('main form').map(f=>f.id), tableLinks: qa('#ordersTableBody a').length })`);
    const types = orders.rows.map((r) => r.type);
    rec.check("INV-ORD-01", `history lists every movement from GET /inventory/orders (${expectedOrders}), newest first`,
      orders.rows.length === expectedOrders && orders.rows[0].type === "outbound" && orders.rows[0].qty === "−10", orders.rows.slice(0, 2));
    rec.check("INV-ORD-02", "each row shows date, type, SKU name, quantity and the user_uuid that created it",
      JSON.stringify(orders.headers) === JSON.stringify(["Fecha", "Tipo", "SKU", "Unidades", "Almacén", "Referencia / seguimiento", "Registrado por"]) &&
        orders.rows.every((r) => r.date && r.date !== "—" && r.sku.length > 3 && r.user.includes(data.userId)), orders.headers);
    rec.check("INV-ORD-03", "entries and exits are visually distinct (↓ Entrada / ↑ Salida, signed quantities)",
      orders.rows.every((r) => (r.type === "inbound" ? r.badge === "↓ Entrada" && r.qty.startsWith("+") : r.badge === "↑ Salida" && r.qty.startsWith("−"))) &&
        types.includes("inbound") && types.includes("outbound"), orders.rows.map((r) => [r.type, r.badge, r.qty]));
    rec.check("INV-ORD-04", "movements created by the current user are marked 'Tú'", orders.rows.every((r) => r.user.includes("Tú")));
    rec.check("INV-ORD-05", "read-only: no edit/delete actions (only the filters and the refresh button)",
      JSON.stringify(orders.buttons) === JSON.stringify(["refreshButton"]) && JSON.stringify(orders.forms) === JSON.stringify(["filtersForm"]) && orders.tableLinks === 0, orders);

    // ---------------------------------------------------------- generales
    rec.check("INV-NAV", "the inventory sub-navigation marks the current view", (await run(`txt('nav[aria-label=Inventario] a[aria-current=page]')`)) === "Movimientos de stock");
    rec.check("INV-HIDDEN", "every .hidden element is display:none on the last page", (await run(`hiddenAudit()`)).shown_without_responsive_override.length === 0);
    rec.check("INV-ERR", "no uncaught exceptions while using the inventory pages", page.state.exceptions.length === 0, page.state.exceptions);
    rec.check("INV-NET", "no request left 127.0.0.1; nothing blocked",
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
  rec.check("INV-CLEAN", "uvicorn and next dev stopped; Chrome profile and the disposable TinyDB/SQLite removed",
    cleanup.profileRemoved && cleanup.apiTempRemoved && (stack ? cleanup.apiStopped && cleanup.nextStopped : true), cleanup);
  return rec;
}
