// Gestor de incidencias (CONTEXT-8) en el backoffice Next.js: /incidents e /incidents/new.
//
// Arranca la API (uvicorn, TinyDB/SQLite desechables, embeddings "hashing" sin descarga) y el
// backoffice, siembra incidencias por HTTP y recorre: resumen, filtros, duplicados, búsqueda,
// casos similares, cambio de estado (también con fallo de red y vuelta atrás), idioma ES/EN y el
// formulario de registro con su ayuda semántica.

import { PAGE_HELPERS, Recorder, killTree, launchChrome, makeTempDir, openPage, removeDir, waitExit, waitFor } from "./lib/harness.mjs";
import { apiCall, click, createUser, setValue, signIn, startStack, submit } from "./lib/backoffice-app.mjs";

const EMAIL = "incidencias-ui@trackflow.com";
const PASSWORD = "incidencias-ui-1234";
const LOST = { title: "Paquete perdido en el almacén de Los Ángeles", description: "El paquete del cliente no aparece en ninguna estantería del almacén de Los Ángeles." };

async function seed(origin) {
  const { token } = await createUser(origin, EMAIL, PASSWORD);
  const create = (body) => apiCall(origin, "POST", "/api/incidents", { token, body });
  const a = await create({ ...LOST, category: "lost_parcel", origin: "customer", branch: "la_warehouse", status: "open" });
  const b = await create({ ...LOST, category: "lost_parcel", origin: "branch", branch: "la_office", status: "open" });
  const c = await create({ title: "Retraso del transportista en Zaragoza", description: "El carrier llega tarde a recoger los envíos del almacén de Zaragoza.", category: "carrier_issue", origin: "internal", branch: "zaragoza_warehouse", status: "in_progress" });
  const d = await create({ title: "Caída del WMS", description: "El sistema de gestión de almacén no responde durante el turno de mañana.", category: "system_failure", origin: "internal", branch: "central", status: "resolved" });
  // Los embeddings se calculan en segundo plano: se espera a que no quede ninguno pendiente.
  await waitFor(async () => (await apiCall(origin, "GET", "/api/incidents/semantic-status", { token })).pending === 0, 30000, 250);
  return { token, ids: { a: a.id, b: b.id, c: c.id, d: d.id } };
}

export async function run({ repoRoot }) {
  const rec = new Recorder("incidents");
  const apiTemp = makeTempDir("incidents-api");
  const browser = await launchChrome();
  let stack = null;
  let cleanup = {};
  // Permite simular una caída de la API solo para el PATCH de estado.
  let blockStatusPatch = false;

  try {
    stack = await startStack(repoRoot, apiTemp);
    const { api, app } = stack;
    const apiHost = new URL(api.origin).host;
    const { token, ids } = await seed(api.origin);
    const policy = ({ method, url }) =>
      url.hostname === "127.0.0.1" && !(blockStatusPatch && method === "PATCH" && url.host === apiHost && url.pathname.endsWith("/status"));
    const page = await openPage(browser, { policy });
    const run = (expression) => page.eval(`(()=>{${PAGE_HELPERS}return ${expression}})()`);
    const settle = (expression, timeout = 30000) => waitFor(() => run(expression), timeout);
    const rowIds = `qa('#incidentsTableBody tr[data-id]').map(r=>Number(r.dataset.id))`;
    const statusSelect = (id) => `#incidentsTableBody tr[data-id="${id}"] select`;

    await signIn(page, app.origin, token);
    await page.eval(`localStorage.setItem('trackflow.lang','es');true`);

    // ============================================================ gestor
    await page.goto(app.origin + "/incidents", 120000);
    await settle(`${rowIds}.length===4 && txt('#summaryTotal')==='4'`, 90000);
    const head = await run(`({title:document.title, h1:txt('#page-title'), toggle:txt('[data-lang-toggle]'), badge:!!qa('header span').find(s=>/backoffice/i.test(txt(s))),
      current:txt('header nav a[aria-current=page]'), lang:document.documentElement.lang})`);
    rec.check("INC-01", "manager loads: title, h1, language toggle (English), nav marks 'Gestor de incidencias'",
      head.title === "Gestor de incidencias | TrackFlow" && head.h1 === "Gestor de incidencias" && head.toggle === "English" && !head.badge && head.current === "Gestor de incidencias" && head.lang === "es", head);

    const summary = await run(`({total:txt('#summaryTotal'), active:txt('#summaryActive'), sla:txt('#summarySla'),
      byStatus:qa('#summaryByStatus button').map(b=>txt(b))})`);
    rec.check("INC-02", "summary: 4 logged, 3 open or in progress, 3 SLA (lost parcels + carrier issues), breakdown by status",
      summary.total === "4" && summary.active === "3" && summary.sla === "3" && summary.byStatus.length === 4 && summary.byStatus[0].startsWith("Abierta"), summary);

    const list = await run(`({ids:${rowIds}, count:txt('#resultsCount'), finalBadge:q('#incidentsTableBody tr[data-id="${ids.d}"] td:nth-child(5) span')?.getAttribute('title'),
      selectInFinal:!!q('${statusSelect(ids.d)}')})`);
    rec.check("INC-03", "list: the 4 incidents, newest first, with count '4 incidencias'",
      JSON.stringify(list.ids) === JSON.stringify([ids.d, ids.c, ids.b, ids.a]) && list.count === "4 incidencias", list);
    rec.check("INC-04", "a final status (resolved) shows a badge 'Estado final' instead of a status selector", list.finalBadge === "Estado final" && !list.selectInFinal, list);

    await page.eval(setValue("#statusFilter", "open"));
    const openOnly = await settle(`(()=>{const v=${rowIds};return v.length===2&&q('#listLoading').classList.contains('hidden')?v:null})()`, 15000);
    rec.check("INC-05", "status filter 'Abierta' lists only the 2 open incidents", JSON.stringify(openOnly) === JSON.stringify([ids.b, ids.a]), openOnly);
    await page.eval(`(()=>{[...document.querySelectorAll('#summaryByStatus button')].find(b=>b.textContent.includes('Resuelta')).click();return true})()`);
    const resolvedOnly = await settle(`(()=>{const v=${rowIds};return q('#statusFilter').value==='resolved'&&v.length===1?v:null})()`, 15000);
    rec.check("INC-06", "clicking 'Resuelta' in the summary filters the list by that status", JSON.stringify(resolvedOnly) === JSON.stringify([ids.d]), resolvedOnly);
    await page.eval(setValue("#statusFilter", ""));
    await settle(`${rowIds}.length===4`, 15000);

    const dup = await settle(`!q('#duplicatesList') ? null : qa('#duplicatesList li').map(li=>txt(li))`, 15000);
    rec.check("INC-07", "possible duplicates: the two identical lost-parcel reports are grouped",
      Array.isArray(dup) && dup.length === 1 && dup[0].includes(`#${ids.a}`) && dup[0].includes(`#${ids.b}`) && dup[0].includes("2 incidencias"), dup);

    await page.eval(setValue("#searchInput", "transportista Zaragoza", "input"));
    await page.eval(submit("#searchForm"));
    const search = await settle(`(()=>{const v=${rowIds};return q('#listLoading').classList.contains('hidden')&&v.length&&vis('#searchInfo').visible?{ids:v,info:txt('#searchInfo'),match:txt('#incidentsTableBody tr[data-id] p span'),clear:vis('#searchClear').visible}:null})()`, 15000);
    rec.check("INC-08", "semantic search: the carrier delay comes first with a match score; info line and 'Quitar búsqueda' shown",
      search && search.ids[0] === ids.c && /Coincidencia \d+ %/.test(search.match) && search.info.includes("transportista Zaragoza") && search.clear, search);
    await page.eval(click("#searchClear"));
    const cleared = await settle(`(()=>{const v=${rowIds};return v.length===4&&!vis('#searchClear').visible?v:null})()`, 15000);
    rec.check("INC-09", "'Quitar búsqueda' restores the full list", !!cleared, cleared);

    await page.eval(`(()=>{[...document.querySelectorAll('#incidentsTableBody tr[data-id="${ids.a}"] button')].find(b=>b.textContent.includes('Ver similares')).click();return true})()`);
    const similar = await settle(`(()=>{const row=q('#incidentsTableBody tr[data-id="${ids.a}"]').nextElementSibling;const t=row&&!row.dataset.id?txt(row):'';return /Casos parecidos/.test(t)&&!/Buscando/.test(t)?t:null})()`, 15000);
    rec.check("INC-10", "'Ver similares' opens the similar cases under the row; the identical report is listed",
      !!similar && similar.includes(`#${ids.b}`), { similar });
    await page.eval(`(()=>{[...document.querySelectorAll('#incidentsTableBody tr[data-id="${ids.a}"] button')].find(b=>b.textContent.includes('Ocultar similares')).click();return true})()`);
    rec.check("INC-11", "'Ocultar similares' closes them", !!(await settle(`!q('#incidentsTableBody tr[data-id="${ids.a}"]').nextElementSibling || !!q('#incidentsTableBody tr[data-id="${ids.a}"]').nextElementSibling.dataset.id`, 5000)));

    // Cambio de estado con la API caída: vuelve al estado anterior y se avisa.
    blockStatusPatch = true;
    await page.eval(setValue(statusSelect(ids.a), "in_progress"));
    const failed = await settle(`(()=>{const s=q('${statusSelect(ids.a)}');return !s.disabled&&vis('#listNotice').visible?{value:s.value,notice:txt('#listNotice')}:null})()`, 15000);
    blockStatusPatch = false;
    rec.check("INC-12", "status change while the API is unreachable: the selector goes back to 'Abierta' and the failure is explained",
      failed && failed.value === "open" &&
        failed.notice === `No se pudo cambiar el estado de la incidencia #${ids.a}. Se ha restaurado el estado anterior. No se pudo conectar con el servidor. Comprueba tu conexión e inténtalo de nuevo.`, failed);

    await page.eval(setValue(statusSelect(ids.a), "in_progress"));
    const changed = await settle(`(()=>{const s=q('${statusSelect(ids.a)}');return s&&s.value==='in_progress'&&/estado cambiado/.test(txt('#listNotice'))?{notice:txt('#listNotice'),options:[...s.options].map(o=>o.value),active:txt('#summaryActive')}:null})()`, 15000);
    rec.check("INC-13", "status change open -> in progress: success notice, new allowed transitions, summary still 3 active",
      changed && changed.notice === `Incidencia #${ids.a}: estado cambiado a «En curso».` &&
        JSON.stringify(changed.options) === JSON.stringify(["in_progress", "resolved", "discarded"]) && changed.active === "3", changed);

    // Idioma: el botón cambia el gestor a inglés y lo recuerda.
    await page.eval(click("[data-lang-toggle]"));
    const en = await settle(`txt('#page-title')==='Incident manager' && ({h1:txt('#page-title'), toggle:txt('[data-lang-toggle]'), nav:txt('header nav a'), lang:document.documentElement.lang,
      notice:txt('#listNotice'), stored:localStorage.getItem('trackflow.lang'), count:txt('#resultsCount')})`, 5000);
    rec.check("INC-14", "language toggle switches the manager (and its nav labels) to English and stores the choice",
      en && en.toggle === "Español" && en.nav === "CSV analyzer" && en.lang === "en" && en.stored === "en" && en.count === "4 incidents" &&
        en.notice === `Incident #${ids.a}: status changed to “In progress”.`, en);
    await page.eval(click("[data-lang-toggle]"));
    await settle(`txt('#page-title')==='Gestor de incidencias'`, 5000);

    // ============================================================ registrar incidencia
    await page.goto(app.origin + "/incidents/new", 120000);
    await settle(`!!q('#incidentForm') && q('#statusInput').options.length===4`, 90000);
    const form = await run(`({title:document.title, status:q('#statusInput').selectedOptions[0].textContent, branch:q('#branchInput').value, category:q('#categoryInput').value,
      origins:qa('#originOptions input').length, assist:txt('#assistState')})`);
    rec.check("NEW-01", "new incident form: status defaults to 'Abierta', branch/category empty, 3 origin options, assist intro",
      form.title === "Registrar incidencia | TrackFlow" && form.status === "Abierta" && form.branch === "" && form.category === "" && form.origins === 3 &&
        form.assist === "Mientras escribes, buscamos incidencias parecidas ya registradas.", form);

    const postsBefore = page.state.responses.filter((r) => r.path === "/api/incidents" && r.type !== "Preflight").length;
    await page.eval(submit("#incidentForm"));
    const errors = await settle(`(()=>{const e=qa('[data-error-for]').filter(p=>!p.classList.contains('hidden')).map(p=>p.dataset.errorFor);return e.length?{errors:e,message:txt('#formMessage')}:null})()`, 5000);
    await settle(`document.activeElement?.name==='origin'`, 3000);
    const focusedName = await run(`document.activeElement?.name`);
    rec.check("NEW-02", "empty submit: an error next to each required field, a summary message, focus on the first field, nothing sent",
      errors && JSON.stringify(errors.errors) === JSON.stringify(["origin", "branch", "category", "title", "description"]) &&
        errors.message === "Revisa los campos marcados antes de enviar." && focusedName === "origin" &&
        page.state.responses.filter((r) => r.path === "/api/incidents" && r.type !== "Preflight").length === postsBefore, { ...errors, focusedName });

    await page.eval(click('#originOptions input[value="branch"]'));
    const highlighted = await settle(`q('#branchField').dataset.highlighted==='true' && ({hint:txt('#branchHint'), originError:!q('[data-error-for=origin]').classList.contains('hidden')})`, 5000);
    rec.check("NEW-03", "choosing origin 'Sede' highlights the site field and clears the origin error",
      highlighted && highlighted.hint === "Estás reportando desde una sede: indica cuál." && !highlighted.originError, highlighted);

    await page.eval(setValue("#titleInput", LOST.title, "input"));
    await page.eval(setValue("#descriptionInput", LOST.description, "input"));
    const assist = await settle(`vis('#assistContent').visible && ({text:txt('#assistContent'), button:txt('#assistContent button')})`, 15000);
    rec.check("NEW-04", "while typing, similar incidents appear with a duplicate warning and a suggested category",
      assist && assist.text.includes(`#${ids.a}`) && assist.text.includes("Puede que esta incidencia ya esté registrada") && assist.button === "Usar «Paquete perdido»", assist);
    await page.eval(click("#assistContent button"));
    const useCategory = await settle(`q('#categoryInput').value==='lost_parcel' && txt('#categoryHint')`, 5000);
    rec.check("NEW-05", "'Usar «Paquete perdido»' fills the category and shows its description", useCategory === "Paquete extraviado en tránsito o en almacén.", { useCategory });

    await page.eval(setValue("#branchInput", "la_warehouse"));
    await page.eval(submit("#incidentForm"));
    const created = await settle(`/registrada correctamente/.test(txt('#formMessage')) && ({message:txt('#formMessage'), link:q('#formMessage a')?.getAttribute('href'),
      title:q('#titleInput').value, status:q('#statusInput').value, branch:q('#branchInput').value})`, 15000);
    // El enlace va pegado al texto (separado con margen, como en el backoffice anterior).
    rec.check("NEW-06", "valid report: success message with a link to the list, and the form is reset",
      created && /^Incidencia #\d+ registrada correctamente\.Ver el listado$/.test(created.message) && created.link === "/incidents" &&
        created.title === "" && created.status === "open" && created.branch === "", created);

    rec.check("INC-ERR", "no uncaught exceptions on the incident pages", page.state.exceptions.length === 0, page.state.exceptions);
    rec.check("INC-NET", "no request left 127.0.0.1", page.state.requests.every((r) => r.host.startsWith("127.0.0.1")), [...new Set(page.state.requests.map((r) => r.host))]);
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
  rec.check("INC-CLEAN", "uvicorn and next dev stopped; Chrome profile and the disposable TinyDB/SQLite removed",
    cleanup.profileRemoved && cleanup.apiTempRemoved && (stack ? cleanup.apiStopped && cleanup.nextStopped : true), cleanup);
  return rec;
}
