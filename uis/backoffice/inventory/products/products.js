// Stock por SKU — GET /inventory/products.
(function () {
  const api = window.TrackflowInventoryApi;
  const ui = window.TrackflowInventoryUi;
  const auth = window.TrackflowAuth;

  const $ = (selector) => document.querySelector(selector);
  const warehouseFilter = $("#warehouseFilter");
  const levelFilter = $("#levelFilter");
  const searchFilter = $("#searchFilter");
  const refreshButton = $("#refreshButton");
  const listAlert = $("#listAlert");
  const listLoading = $("#listLoading");
  const tableBody = $("#skuTableBody");
  const emptyState = $("#emptyState");
  const resultsCount = $("#resultsCount");

  let skus = [];

  function otherWarehouses(sku) {
    return Object.entries(sku.stock_by_warehouse).filter(([code, units]) => code !== sku.warehouse && units !== 0);
  }

  function matchesFilters(sku) {
    const level = ui.stockLevel(sku.current_stock).key;
    if (warehouseFilter.value && sku.warehouse !== warehouseFilter.value) return false;
    if (levelFilter.value === "attention" && level === "ok") return false;
    if (levelFilter.value === "out" && level !== "out") return false;
    const term = searchFilter.value.trim().toLowerCase();
    return !term || [sku.sku, sku.name, sku.client_name].some((value) => value.toLowerCase().includes(term));
  }

  function actionLink(label, path, sku) {
    const link = ui.el(
      "a",
      "inline-flex items-center justify-center whitespace-nowrap rounded-lg border border-cyan-300 bg-white px-3 py-1.5 text-xs font-bold text-cyan-800 transition hover:bg-cyan-50 focus:outline-none focus:ring-4 focus:ring-cyan-200",
      label,
    );
    link.href = auth.pageUrl(`${path}?sku_id=${encodeURIComponent(sku.id)}`);
    link.setAttribute("aria-label", `${label} de ${sku.sku}`);
    return link;
  }

  function renderRow(sku) {
    const level = ui.stockLevel(sku.current_stock);
    const tint = { out: "bg-red-50/60", low: "bg-amber-50/60", ok: "" }[level.key];
    const row = ui.el("tr", `align-top ${tint}`);
    row.dataset.skuId = sku.id;
    row.dataset.level = level.key;

    const code = ui.el("td", "whitespace-nowrap px-3 py-3 font-mono text-xs font-bold text-slate-900", sku.sku);
    const name = ui.el("td", "px-3 py-3 font-semibold text-slate-900", sku.name);
    const client = ui.el("td", "px-3 py-3 text-slate-700", sku.client_name);
    const category = ui.el("td", "px-3 py-3 text-slate-700", ui.CATEGORY_LABELS[sku.category] || sku.category);
    const warehouse = ui.el("td", "whitespace-nowrap px-3 py-3 text-slate-700", ui.warehouseName(sku.warehouse));

    const stock = ui.el("td", "px-3 py-3");
    stock.append(ui.stockBadge(sku.current_stock));
    for (const [otherCode, units] of otherWarehouses(sku)) {
      stock.append(ui.el("p", "mt-1 text-xs text-slate-500", `En ${ui.warehouseName(otherCode)}: ${ui.formatUnits(units)}`));
    }

    const actions = ui.el("td", "px-3 py-3");
    const wrapper = ui.el("div", "flex flex-wrap gap-2");
    wrapper.append(
      actionLink("Registrar entrada", "inventory/orders/inbound/", sku),
      actionLink("Registrar salida", "inventory/orders/outbound/", sku),
    );
    actions.append(wrapper);

    row.append(code, name, client, category, warehouse, stock, actions);
    return row;
  }

  function renderSummary() {
    const levels = skus.map((sku) => ui.stockLevel(sku.current_stock).key);
    $("#totalCount").textContent = String(skus.length);
    $("#lowCount").textContent = String(levels.filter((key) => key === "low").length);
    $("#outCount").textContent = String(levels.filter((key) => key === "out").length);
  }

  function render() {
    const visible = skus.filter(matchesFilters);
    tableBody.replaceChildren(...visible.map(renderRow));
    resultsCount.textContent = skus.length
      ? `Mostrando ${visible.length} de ${skus.length} SKUs.`
      : "";
    emptyState.hidden = visible.length > 0;
    emptyState.textContent = skus.length
      ? "Ningún SKU coincide con los filtros."
      : "Todavía no hay SKUs registrados.";
    renderSummary();
  }

  async function load() {
    listLoading.hidden = false;
    refreshButton.disabled = true;
    ui.hideAlert(listAlert);
    try {
      skus = await api.listSkus();
      render();
    } catch (error) {
      if (error instanceof auth.SessionExpiredError) return;
      ui.showAlert(listAlert, "error", `No se pudo cargar el stock. ${error.message}`);
      emptyState.hidden = true;
    } finally {
      listLoading.hidden = true;
      refreshButton.disabled = false;
    }
  }

  for (const control of [warehouseFilter, levelFilter]) control.addEventListener("change", render);
  searchFilter.addEventListener("input", render);
  $("#filtersForm").addEventListener("submit", (event) => event.preventDefault());
  refreshButton.addEventListener("click", load);

  load();
})();
