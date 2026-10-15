// Movimientos de stock — GET /inventory/orders. Solo lectura: sin acciones de edición ni borrado.
(function () {
  const api = window.TrackflowInventoryApi;
  const ui = window.TrackflowInventoryUi;
  const auth = window.TrackflowAuth;

  const $ = (selector) => document.querySelector(selector);
  const typeFilter = $("#typeFilter");
  const warehouseFilter = $("#warehouseFilter");
  const searchFilter = $("#searchFilter");
  const refreshButton = $("#refreshButton");
  const listAlert = $("#listAlert");
  const listLoading = $("#listLoading");
  const userNote = $("#userNote");
  const tableBody = $("#ordersTableBody");
  const emptyState = $("#emptyState");
  const resultsCount = $("#resultsCount");

  const TYPE_STYLES = {
    inbound: {
      label: "↓ Entrada",
      badge: "border-emerald-200 bg-emerald-50 text-emerald-800",
      edge: "border-l-4 border-l-emerald-400",
      quantity: "text-emerald-700",
      sign: "+",
    },
    outbound: {
      label: "↑ Salida",
      badge: "border-rose-200 bg-rose-50 text-rose-800",
      edge: "border-l-4 border-l-rose-400",
      quantity: "text-rose-700",
      sign: "−",
    },
  };

  let orders = [];
  let currentUserId = null;

  function detail(order) {
    if (order.order_type === "inbound") return `Ref. ${order.reference}`;
    return order.tracking_number ? `Seguimiento ${order.tracking_number}` : "—";
  }

  function subtype(order) {
    return order.order_type === "inbound" ? "Recepción de mercancía" : ui.EXIT_TYPE_LABELS[order.exit_type] || order.exit_type;
  }

  function matchesFilters(order) {
    if (typeFilter.value && order.order_type !== typeFilter.value) return false;
    if (warehouseFilter.value && order.warehouse !== warehouseFilter.value) return false;
    const term = searchFilter.value.trim().toLowerCase();
    if (!term) return true;
    return [order.sku.sku, order.sku.name, order.sku.client_name, order.reference, order.tracking_number]
      .some((value) => value && value.toLowerCase().includes(term));
  }

  function renderRow(order) {
    const style = TYPE_STYLES[order.order_type];
    const row = ui.el("tr", "align-top");
    row.dataset.orderType = order.order_type;

    const date = ui.el("td", `whitespace-nowrap px-3 py-3 text-slate-700 ${style.edge}`, ui.formatDateTime(order.created_at));
    date.title = order.created_at;

    const type = ui.el("td", "px-3 py-3");
    type.append(
      ui.el("span", `inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-bold ${style.badge}`, style.label),
      ui.el("p", "mt-1 text-xs text-slate-500", subtype(order)),
    );

    const sku = ui.el("td", "px-3 py-3");
    sku.append(
      ui.el("p", "font-mono text-xs font-bold text-slate-900", order.sku.sku),
      ui.el("p", "text-slate-800", order.sku.name),
      ui.el("p", "text-xs text-slate-500", order.sku.client_name),
    );

    const quantity = ui.el(
      "td",
      `whitespace-nowrap px-3 py-3 text-right font-bold ${style.quantity}`,
      `${style.sign}${Number(order.quantity).toLocaleString("es-ES")}`,
    );
    quantity.setAttribute("aria-label", `${order.order_type === "inbound" ? "Entran" : "Salen"} ${ui.formatUnits(order.quantity)}`);

    const warehouse = ui.el("td", "whitespace-nowrap px-3 py-3 text-slate-700", ui.warehouseName(order.warehouse));
    const reference = ui.el("td", "px-3 py-3 font-mono text-xs text-slate-700", detail(order));

    const user = ui.el("td", "px-3 py-3");
    user.append(ui.el("p", "break-all font-mono text-xs text-slate-700", order.user_uuid));
    if (currentUserId && order.user_uuid === currentUserId) {
      user.append(ui.el("span", "mt-1 inline-block rounded-full bg-cyan-100 px-2 py-0.5 text-xs font-bold text-cyan-800", "Tú"));
    }

    row.append(date, type, sku, quantity, warehouse, reference, user);
    return row;
  }

  function render() {
    const visible = orders.filter(matchesFilters);
    tableBody.replaceChildren(...visible.map(renderRow));
    const entries = orders.filter((order) => order.order_type === "inbound").length;
    resultsCount.textContent = orders.length
      ? `Mostrando ${visible.length} de ${orders.length} movimientos (${entries} entradas, ${orders.length - entries} salidas).`
      : "";
    emptyState.hidden = visible.length > 0;
    emptyState.textContent = orders.length
      ? "Ningún movimiento coincide con los filtros."
      : "Todavía no hay movimientos de stock registrados.";
  }

  async function load() {
    listLoading.hidden = false;
    refreshButton.disabled = true;
    ui.hideAlert(listAlert);
    const [ordersResult, userResult] = await Promise.allSettled([api.listOrders(), api.getCurrentUser()]);
    listLoading.hidden = true;
    refreshButton.disabled = false;

    const failures = [ordersResult, userResult].filter((result) => result.status === "rejected");
    if (failures.some((result) => result.reason instanceof auth.SessionExpiredError)) return;

    // Sin el usuario actual solo se pierde la marca "Tú": se avisa, pero el historial se muestra.
    currentUserId = userResult.status === "fulfilled" ? userResult.value.id : null;
    userNote.hidden = userResult.status === "fulfilled";
    userNote.textContent = userResult.status === "fulfilled"
      ? ""
      : `No se pudo identificar tu usuario (${userResult.reason.message}); tus movimientos no aparecen marcados.`;

    if (ordersResult.status === "rejected") {
      ui.showAlert(listAlert, "error", `No se pudo cargar el historial. ${ordersResult.reason.message}`);
      emptyState.hidden = true;
      return;
    }
    orders = ordersResult.value;
    render();
  }

  for (const control of [typeFilter, warehouseFilter]) control.addEventListener("change", render);
  searchFilter.addEventListener("input", render);
  $("#filtersForm").addEventListener("submit", (event) => event.preventDefault());
  refreshButton.addEventListener("click", load);

  load();
})();
