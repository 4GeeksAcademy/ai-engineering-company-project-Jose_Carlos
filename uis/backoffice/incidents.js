// Panel de resumen, posibles duplicados y listado del gestor de incidencias.
// Cada bloque carga por separado: si uno falla, los demás siguen funcionando.
const {
  BRANCHES,
  CATEGORIES,
  ORIGINS,
  SLA_CATEGORIES,
  STATUSES,
  STATUS_COLORS,
  STATUS_TRANSITIONS,
  api,
  el,
  errorMessage,
  fillSelect,
  formatDate,
  statusBadge,
  t,
} = TrackflowIncidents;

const filterSelects = {
  status: document.querySelector("#statusFilter"),
  origin: document.querySelector("#originFilter"),
  branch: document.querySelector("#branchFilter"),
  category: document.querySelector("#categoryFilter"),
};

const summaryLoading = document.querySelector("#summaryLoading");
const summaryError = document.querySelector("#summaryError");
const summaryContent = document.querySelector("#summaryContent");

const duplicatesState = document.querySelector("#duplicatesState");
const duplicatesList = document.querySelector("#duplicatesList");

const searchForm = document.querySelector("#searchForm");
const searchInput = document.querySelector("#searchInput");
const searchClear = document.querySelector("#searchClear");
const searchInfo = document.querySelector("#searchInfo");
const resultsCount = document.querySelector("#resultsCount");
const listNotice = document.querySelector("#listNotice");
const listLoading = document.querySelector("#listLoading");
const listError = document.querySelector("#listError");
const listEmpty = document.querySelector("#listEmpty");
const listTable = document.querySelector("#listTable");
const tableBody = document.querySelector("#incidentsTableBody");

let incidents = [];
let summary = null;
let duplicateGroups = null;
let activeSearch = "";
let listRequestId = 0;
// "loading" | "error" | "ready", para volver a pintar al cambiar de idioma
let listState = "loading";
let listErrorKey = "list.error";
let summaryState = "loading";
let duplicatesStateName = "loading";
let lastNotice = null;

function toggle(element, visible, display = "block") {
  element.classList.toggle("hidden", !visible);
  element.classList.toggle(display, visible);
}

function currentFilters() {
  return Object.fromEntries(Object.entries(filterSelects).map(([field, select]) => [field, select.value]));
}

// =========================================================
// RESUMEN
// =========================================================

function renderBreakdown(containerId, field, values, counts) {
  const container = document.querySelector(containerId);
  container.replaceChildren();
  const max = Math.max(1, ...values.map((value) => counts[value] || 0));

  values.forEach((value) => {
    const count = counts[value] || 0;
    const label = t(`${field}.${value}`);

    // Cada fila filtra el listado por ese valor.
    const row = el(
      "button",
      "flex min-h-11 w-full items-center gap-3 py-2 text-left transition hover:bg-cyan-50 focus:outline-none focus:ring-2 focus:ring-cyan-300",
    );
    row.type = "button";
    row.title = t("summary.filterBy", { label });
    row.addEventListener("click", () => {
      filterSelects[field].value = value;
      loadList();
      document.querySelector("#list-title").scrollIntoView({ behavior: "smooth", block: "start" });
    });

    const term = el("span", "flex w-1/2 shrink-0 items-center gap-2 text-sm font-medium text-slate-700", label);
    if (field === "category" && SLA_CATEGORIES.includes(value)) {
      term.append(el("span", "rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-bold text-amber-900", t("common.sla")));
    }

    const bar = el("span", "h-2 flex-1 overflow-hidden rounded-full bg-cyan-50");
    const fill = el("span", "block h-full rounded-full bg-cyan-600");
    fill.style.width = `${(count / max) * 100}%`;
    bar.append(fill);

    const number = el("span", "w-10 shrink-0 text-right text-sm font-bold text-slate-900", String(count));

    row.append(term, bar, number);
    container.append(row);
  });
}

function renderSummary() {
  toggle(summaryLoading, summaryState === "loading", "flex");
  toggle(summaryError, summaryState === "error", "flex");
  toggle(summaryContent, summaryState === "ready");

  if (summaryState === "error") {
    document.querySelector("#summaryErrorText").textContent = t("summary.error");
  }
  if (summaryState !== "ready") return;

  document.querySelector("#summaryTotal").textContent = String(summary.total);
  document.querySelector("#summaryActive").textContent = String(
    summary.by_status.open + summary.by_status.in_progress,
  );
  document.querySelector("#summarySla").textContent = String(
    SLA_CATEGORIES.reduce((total, category) => total + (summary.by_category[category] || 0), 0),
  );

  renderBreakdown("#summaryByStatus", "status", STATUSES, summary.by_status);
  renderBreakdown("#summaryByCategory", "category", CATEGORIES, summary.by_category);
  renderBreakdown("#summaryByOrigin", "origin", ORIGINS, summary.by_origin);
  renderBreakdown("#summaryByBranch", "branch", BRANCHES, summary.by_branch);
}

async function loadSummary() {
  // En las recargas tras un cambio de estado no se oculta el resumen ya pintado.
  if (summary === null) {
    summaryState = "loading";
    renderSummary();
  }
  try {
    summary = await api.summary();
    summaryState = "ready";
  } catch (error) {
    if (error instanceof TrackflowAuth.SessionExpiredError) return;
    summary = null;
    summaryState = "error";
  }
  renderSummary();
}

// =========================================================
// POSIBLES DUPLICADOS
// =========================================================

function renderDuplicates() {
  const hasGroups = duplicatesStateName === "ready" && duplicateGroups.length > 0;
  toggle(duplicatesState, !hasGroups);
  toggle(duplicatesList, hasGroups);
  duplicatesList.replaceChildren();

  if (!hasGroups) {
    const key = { loading: "duplicates.loading", error: "duplicates.error", ready: "duplicates.empty" }[
      duplicatesStateName
    ];
    duplicatesState.textContent = t(key);
    return;
  }

  duplicateGroups.forEach((group) => {
    const item = el(
      "li",
      "flex flex-col gap-3 rounded-xl border border-amber-200 bg-amber-50 p-4 sm:flex-row sm:items-center sm:justify-between",
    );

    const info = el("div", "min-w-0");
    info.append(el("p", "font-bold text-slate-900", group.title));
    const details = [
      t("duplicates.count", { n: group.size }),
      t(`category.${group.category}`),
      group.branches.map((branch) => t(`branch.${branch}`)).join(", "),
      group.incident_ids.map((id) => `#${id}`).join(" "),
    ];
    info.append(el("p", "mt-1 text-sm text-slate-700", details.join(" · ")));

    const button = el(
      "button",
      "min-h-11 shrink-0 rounded-lg border border-amber-400 bg-white px-4 py-2 text-sm font-bold text-amber-900 transition hover:bg-amber-100 focus:outline-none focus:ring-4 focus:ring-amber-200",
      t("duplicates.view"),
    );
    button.type = "button";
    button.addEventListener("click", () => {
      searchInput.value = group.title;
      runSearch();
      document.querySelector("#list-title").scrollIntoView({ behavior: "smooth", block: "start" });
    });

    item.append(info, button);
    duplicatesList.append(item);
  });
}

async function loadDuplicates() {
  try {
    duplicateGroups = await api.duplicates();
    duplicatesStateName = "ready";
  } catch (error) {
    if (error instanceof TrackflowAuth.SessionExpiredError) return;
    duplicatesStateName = "error";
  }
  renderDuplicates();
}

// =========================================================
// LISTADO
// =========================================================

function showNotice(type, key, params) {
  lastNotice = { type, key, params };
  listNotice.textContent = t(key, params);
  listNotice.className = `mt-5 rounded-xl border p-4 text-sm ${
    type === "error"
      ? "border-red-200 bg-red-50 font-semibold text-red-800"
      : "border-green-200 bg-green-50 text-green-900"
  }`;
}

function hideNotice() {
  lastNotice = null;
  listNotice.classList.add("hidden");
}

function statusSelectClass(status) {
  return `min-h-11 w-full min-w-36 rounded-lg px-3 py-2 text-sm font-bold ring-1 focus:outline-none focus:ring-4 disabled:cursor-not-allowed disabled:opacity-70 ${STATUS_COLORS[status]}`;
}

function renderStatusCell(incident) {
  const cell = el("td", "py-4 pr-4 align-top");
  const transitions = STATUS_TRANSITIONS[incident.status];

  // Estado final: no hay nada que cambiar.
  if (transitions.length === 0) {
    const badge = statusBadge(incident.status);
    badge.title = t("list.finalStatus");
    cell.append(badge);
    return cell;
  }

  const select = el("select", statusSelectClass(incident.status));
  select.setAttribute("aria-label", t("list.changeStatus", { id: incident.id }));
  [incident.status, ...transitions].forEach((status) => {
    select.append(new Option(t(`status.${status}`), status));
  });
  select.value = incident.status;

  select.addEventListener("change", async () => {
    const previous = incident.status;
    const next = select.value;

    // Cambio optimista: el estado se ve aplicado mientras la petición está en curso.
    select.className = statusSelectClass(next);
    select.disabled = true;
    hideNotice();

    try {
      const updated = await api.updateStatus(incident.id, next);
      incidents = incidents.map((item) => (item.id === updated.id ? { ...item, ...updated } : item));
      renderList();
      showNotice("success", "list.statusUpdated", { id: updated.id, status: t(`status.${updated.status}`) });
      loadSummary();
      loadDuplicates();
    } catch (error) {
      if (error instanceof TrackflowAuth.SessionExpiredError) return;
      // Fallo: el estado visual vuelve al valor anterior y se avisa al usuario.
      select.value = previous;
      select.className = statusSelectClass(previous);
      select.disabled = false;
      listNotice.textContent = `${t("list.statusFailed", { id: incident.id })} ${errorMessage(error)}`;
      listNotice.className = "mt-5 rounded-xl border border-red-200 bg-red-50 p-4 text-sm font-semibold text-red-800";
      lastNotice = null;
    }
  });

  cell.append(select);
  return cell;
}

function renderSimilarRow(incident, button) {
  const row = el("tr", "bg-cyan-50");
  const cell = el("td", "px-4 py-4");
  cell.colSpan = 6;
  cell.append(el("p", "text-xs font-bold uppercase tracking-wide text-cyan-800", t("list.similarTitle")));
  const content = el("div", "mt-2 text-sm text-slate-700", t("list.similarLoading"));
  cell.append(content);
  row.append(cell);

  api
    .similar(incident.id)
    .then((similar) => {
      content.replaceChildren();
      if (similar.length === 0) {
        content.textContent = t("list.similarEmpty");
        return;
      }
      const list = el("ul", "space-y-2");
      similar.forEach((item) => {
        const line = el("li", "flex flex-wrap items-center gap-2");
        line.append(
          el("span", "font-bold text-slate-900", `#${item.id}`),
          el("span", "text-slate-800", item.title),
          statusBadge(item.status),
          el("span", "text-xs text-slate-500", t("list.match", { n: Math.round(item.score * 100) })),
          el("span", "text-xs text-slate-500", `${t(`branch.${item.branch}`)} · ${formatDate(item.created_at)}`),
        );
        list.append(line);
      });
      content.append(list);
    })
    .catch((error) => {
      if (error instanceof TrackflowAuth.SessionExpiredError) return;
      content.textContent = t("list.similarError");
    });

  button.textContent = t("list.similarHide");
  return row;
}

function renderRow(incident) {
  const row = el("tr");
  row.dataset.id = incident.id;

  const main = el("td", "max-w-md py-4 pr-4 align-top");
  main.append(el("p", "font-bold text-slate-900", `#${incident.id} · ${incident.title}`));
  if (incident.description !== incident.title) {
    main.append(el("p", "mt-1 line-clamp-2 text-sm text-slate-600", incident.description));
  }
  const meta = el("p", "mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-500", formatDate(incident.created_at));
  if (incident.score !== undefined) {
    meta.append(
      el(
        "span",
        "rounded-full bg-cyan-100 px-2 py-0.5 font-semibold text-cyan-800",
        t("list.match", { n: Math.round(incident.score * 100) }),
      ),
    );
  }
  main.append(meta);

  const category = el("td", "py-4 pr-4 align-top");
  const chip = el(
    "span",
    "inline-flex whitespace-nowrap rounded-full bg-cyan-100 px-2 py-0.5 text-xs font-semibold text-cyan-800",
    t(`category.${incident.category}`),
  );
  chip.title = t(`categoryHint.${incident.category}`);
  category.append(chip);

  const origin = el("td", "py-4 pr-4 align-top text-slate-700", t(`origin.${incident.origin}`));
  const branch = el("td", "py-4 pr-4 align-top text-slate-700", t(`branch.${incident.branch}`));

  const actions = el("td", "py-4 align-top text-right");
  const similarButton = el(
    "button",
    "min-h-11 whitespace-nowrap rounded-lg border border-cyan-300 bg-white px-3 py-2 text-xs font-bold text-cyan-800 transition hover:bg-cyan-50 focus:outline-none focus:ring-4 focus:ring-cyan-200",
    t("list.similar"),
  );
  similarButton.type = "button";
  let similarRow = null;
  similarButton.addEventListener("click", () => {
    if (similarRow) {
      similarRow.remove();
      similarRow = null;
      similarButton.textContent = t("list.similar");
      return;
    }
    similarRow = renderSimilarRow(incident, similarButton);
    row.after(similarRow);
  });
  actions.append(similarButton);

  row.append(main, category, origin, branch, renderStatusCell(incident), actions);
  return row;
}

// Pinta el listado según su estado: cargando, error, vacío o con datos.
function renderList() {
  const isReady = listState === "ready";
  const isEmpty = isReady && incidents.length === 0;

  toggle(listLoading, listState === "loading", "flex");
  toggle(listError, listState === "error", "flex");
  toggle(listEmpty, isEmpty);
  toggle(listTable, isReady && !isEmpty);
  toggle(searchClear, activeSearch !== "");
  toggle(searchInfo, activeSearch !== "" && isReady);
  searchInfo.textContent = t("list.searchInfo", { q: activeSearch });
  tableBody.replaceChildren();

  if (listState === "error") {
    document.querySelector("#listErrorText").textContent = t(listErrorKey);
  }

  if (!isReady) {
    resultsCount.textContent = "";
    return;
  }

  resultsCount.textContent =
    incidents.length === 1 ? t("list.count.one") : t("list.count.many", { n: incidents.length });

  if (isEmpty) {
    const hasFilters = Object.values(currentFilters()).some(Boolean);
    listEmpty.textContent = activeSearch
      ? t("list.emptySearch")
      : t(hasFilters ? "list.emptyFiltered" : "list.empty");
    return;
  }

  incidents.forEach((incident) => tableBody.append(renderRow(incident)));
}

async function loadList() {
  const requestId = ++listRequestId;
  listState = "loading";
  hideNotice();
  renderList();

  try {
    const result = activeSearch
      ? await api.search(activeSearch, currentFilters())
      : await api.list(currentFilters());
    // Si el usuario ha cambiado los filtros mientras tanto, esta respuesta ya no vale.
    if (requestId !== listRequestId) return;
    incidents = result;
    listState = "ready";
  } catch (error) {
    if (error instanceof TrackflowAuth.SessionExpiredError || requestId !== listRequestId) return;
    incidents = [];
    listState = "error";
    listErrorKey = activeSearch && error.status === 503 ? "list.searchError" : "list.error";
  }
  renderList();
}

function runSearch() {
  activeSearch = searchInput.value.trim();
  loadList();
}

// =========================================================
// INICIO
// =========================================================

function renderFilterOptions() {
  fillSelect(filterSelects.status, STATUSES, "status", "common.all");
  fillSelect(filterSelects.origin, ORIGINS, "origin", "common.all");
  fillSelect(filterSelects.branch, BRANCHES, "branch", "common.allFem");
  fillSelect(filterSelects.category, CATEGORIES, "category", "common.allFem");
}

Object.values(filterSelects).forEach((select) => select.addEventListener("change", loadList));

searchForm.addEventListener("submit", (event) => {
  event.preventDefault();
  runSearch();
});

searchClear.addEventListener("click", () => {
  searchInput.value = "";
  runSearch();
});

document.querySelector("#listRetry").addEventListener("click", loadList);
document.querySelector("#summaryRetry").addEventListener("click", () => {
  summary = null;
  loadSummary();
});

// Al cambiar de idioma se vuelve a pintar todo lo generado por JavaScript.
document.addEventListener("trackflow:langchange", () => {
  renderFilterOptions();
  renderSummary();
  renderDuplicates();
  renderList();
  if (lastNotice) showNotice(lastNotice.type, lastNotice.key, lastNotice.params);
});

renderFilterOptions();
renderDuplicates();
loadSummary();
loadDuplicates();
loadList();
