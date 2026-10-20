// Directorio de proveedores (CONTEXT-7) en el backoffice Next.js: /suppliers.
//
// Arranca la API (uvicorn, TinyDB/SQLite desechables) y el backoffice, siembra dos proveedores por
// HTTP y recorre: listado y filtros, validación del alta, moneda según país, alta correcta,
// edición de la tarifa en línea y suspender / reactivar.

import { PAGE_HELPERS, Recorder, killTree, launchChrome, makeTempDir, openPage, removeDir, waitExit, waitFor } from "./lib/harness.mjs";
import { apiCall, click, createUser, setValue, signIn, startStack, submit } from "./lib/backoffice-app.mjs";

const EMAIL = "proveedores-ui@trackflow.com";
const PASSWORD = "proveedores-ui-1234";

async function seed(origin) {
  const { token } = await createUser(origin, EMAIL, PASSWORD);
  const create = (body) => apiCall(origin, "POST", "/suppliers", { token, body });
  const usa = await create({ name: "Pacific Last Mile", country: "USA", categories: ["carrier_last_mile"], rate_per_shipment: 4.5, currency: "USD", status: "active", service_zone: "West Coast", contact_email: null, notes: null });
  const spain = await create({ name: "Embalajes Ebro", country: "Spain", categories: ["packaging_materials"], rate_per_shipment: 1.2, currency: "EUR", status: "suspended", service_zone: "Aragón", contact_email: null, notes: null });
  return { token, ids: { usa: usa.id, spain: spain.id } };
}

export async function run({ repoRoot }) {
  const rec = new Recorder("suppliers");
  const apiTemp = makeTempDir("suppliers-api");
  const browser = await launchChrome();
  let stack = null;
  let cleanup = {};

  try {
    stack = await startStack(repoRoot, apiTemp);
    const { api, app } = stack;
    const { token, ids } = await seed(api.origin);
    const page = await openPage(browser, { policy: ({ url }) => url.hostname === "127.0.0.1" });
    const run = (expression) => page.eval(`(()=>{${PAGE_HELPERS}return ${expression}})()`);
    const settle = (expression, timeout = 30000) => waitFor(() => run(expression), timeout);
    const names = `qa('#suppliersTableBody tr[data-id]').map(r=>txt(r.cells[0].querySelector('p')))`;
    const row = (id) => `#suppliersTableBody tr[data-id="${id}"]`;

    await signIn(page, app.origin, token);
    await page.goto(app.origin + "/suppliers", 120000);
    await settle(`${names}.length===2 && q('#listLoading').classList.contains('hidden')`, 90000);

    const list = await run(`({title:document.title, h1:txt('#page-title'), count:txt('#resultsCount'), names:${names},
      usa:{rate:txt('${row(ids.usa)} td:nth-child(3) p'), status:txt('${row(ids.usa)} td:nth-child(4)'), action:txt('${row(ids.usa)} td:nth-child(6) button'), cats:txt('${row(ids.usa)} td:nth-child(2)')},
      spain:{rate:txt('${row(ids.spain)} td:nth-child(3) p'), status:txt('${row(ids.spain)} td:nth-child(4)'), action:txt('${row(ids.spain)} td:nth-child(6) button')}})`);
    rec.check("SUP-01", "directory loads: title, h1 and both suppliers with count '2 proveedores'",
      list.title === "Directorio de proveedores | TrackFlow" && list.h1 === "Directorio de proveedores" && list.count === "2 proveedores" && list.names.length === 2, list);
    rec.check("SUP-02", "each row shows rate in its currency, category label, status and the matching action",
      list.usa.rate.includes("4,50") && list.usa.rate.includes("US$") && list.usa.cats === "Carrier última milla" && list.usa.status === "Activo" && list.usa.action === "Suspender" &&
        list.spain.rate.includes("1,20") && list.spain.rate.includes("€") && list.spain.status === "Suspendido" && list.spain.action === "Reactivar", list);

    await page.eval(setValue("#countryFilter", "Spain"));
    const spainOnly = await settle(`(()=>{const n=${names};return n.length===1&&q('#listLoading').classList.contains('hidden')?n:null})()`, 15000);
    rec.check("SUP-03", "country filter 'Spain' lists only the Spanish supplier", JSON.stringify(spainOnly) === JSON.stringify(["Embalajes Ebro"]), spainOnly);
    await page.eval(setValue("#countryFilter", "USA"));
    await page.eval(setValue("#categoryFilter", "packaging_materials"));
    const none = await settle(`txt('#resultsCount')==='0 proveedores' && txt('#suppliersTableBody')`, 15000);
    rec.check("SUP-04", "filters with no match: '0 proveedores' and an empty-state row", none === "No hay proveedores con estos filtros.", { none });
    await page.eval(setValue("#categoryFilter", ""));
    await page.eval(setValue("#countryFilter", ""));
    await settle(`${names}.length===2`, 15000);

    // ---------------------------------------------------------- alta
    const postsBefore = page.state.responses.filter((r) => r.path === "/suppliers" && r.type !== "Preflight").length;
    await page.eval(submit("#createForm"));
    const invalid = await settle(`vis('#createMessage').visible && txt('#createMessage')`, 5000);
    rec.check("SUP-05", "empty create form: all client-side errors in one message, nothing sent",
      invalid === "El nombre es obligatorio. Selecciona un país. Selecciona al menos una categoría. La tarifa debe ser mayor que 0." &&
        page.state.responses.filter((r) => r.path === "/suppliers" && r.type !== "Preflight").length === postsBefore, { invalid });

    await page.eval(setValue("#countryInput", "Spain"));
    rec.check("SUP-06", "choosing the contract country fills the currency (Spain -> EUR)", (await settle(`q('#currencyInput').value==='EUR'`, 5000)) === true);

    await page.eval(setValue("#nameInput", "Limpiezas Delicias", "input"));
    await page.eval(click('#categoriesInput input[value="cleaning_and_facilities"]'));
    await page.eval(setValue("#rateInput", "2.75", "input"));
    await page.eval(submit("#createForm"));
    const created = await settle(`/registrado con id/.test(txt('#createMessage')) && ${names}.length===3 && ({message:txt('#createMessage'), name:q('#nameInput').value, currency:q('#currencyInput').value, names:${names}})`, 15000);
    rec.check("SUP-07", "valid supplier: confirmation, form cleared and the list reloaded with the new supplier",
      created && /^Proveedor "Limpiezas Delicias" registrado con id \d+\.$/.test(created.message) && created.name === "" && created.currency === "" &&
        created.names.includes("Limpiezas Delicias"), created);

    // ---------------------------------------------------------- tarifa en línea
    const rateInput = `${row(ids.usa)} td:nth-child(3) input`;
    await page.eval(setValue(rateInput, "0", "input"));
    await page.eval(submit(`${row(ids.usa)} td:nth-child(3) form`));
    const rateError = await settle(`vis('${row(ids.usa)} td:nth-child(3) [role=alert]').visible && txt('${row(ids.usa)} td:nth-child(3) [role=alert]')`, 5000);
    rec.check("SUP-08", "inline rate editor rejects 0 with a message next to it", rateError === "La tarifa debe ser mayor que 0.", { rateError });
    await page.eval(setValue(rateInput, "6.25", "input"));
    await page.eval(submit(`${row(ids.usa)} td:nth-child(3) form`));
    const newRate = await settle(`/6,25/.test(txt('${row(ids.usa)} td:nth-child(3) p')) && ({rate:txt('${row(ids.usa)} td:nth-child(3) p'), errorHidden:!vis('${row(ids.usa)} td:nth-child(3) [role=alert]').visible})`, 15000);
    rec.check("SUP-09", "saving a valid rate updates the row in place (PATCH /suppliers/{id}/rate)", newRate && newRate.errorHidden, newRate);

    // ---------------------------------------------------------- suspender / reactivar
    await page.eval(click(`${row(ids.usa)} td:nth-child(6) button`));
    const suspended = await settle(`txt('${row(ids.usa)} td:nth-child(4)')==='Suspendido' && txt('${row(ids.usa)} td:nth-child(6) button')`, 15000);
    rec.check("SUP-10", "'Suspender' suspends the supplier and the action becomes 'Reactivar'", suspended === "Reactivar", { suspended });
    await page.eval(click(`${row(ids.usa)} td:nth-child(6) button`));
    const active = await settle(`txt('${row(ids.usa)} td:nth-child(4)')==='Activo' && txt('${row(ids.usa)} td:nth-child(6) button')`, 15000);
    rec.check("SUP-11", "'Reactivar' makes it active again", active === "Suspender", { active });

    rec.check("SUP-ERR", "no uncaught exceptions on the suppliers page", page.state.exceptions.length === 0, page.state.exceptions);
    rec.check("SUP-NET", "no request left 127.0.0.1", page.state.requests.every((r) => r.host.startsWith("127.0.0.1")));
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
  rec.check("SUP-CLEAN", "uvicorn and next dev stopped; Chrome profile and the disposable TinyDB/SQLite removed",
    cleanup.profileRemoved && cleanup.apiTempRemoved && (stack ? cleanup.apiStopped && cleanup.nextStopped : true), cleanup);
  return rec;
}
