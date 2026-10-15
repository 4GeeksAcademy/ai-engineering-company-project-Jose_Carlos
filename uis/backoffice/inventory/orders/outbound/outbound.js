// Salida de stock — POST /inventory/orders/outbound (StockExit): despacho a cliente o pérdida.
//
// Al elegir un SKU se pide su stock actual a la API (GET /inventory/products/{id}) y se muestra
// el disponible en el almacén de salida antes de enviar. Si la cantidad lo supera, se avisa en el
// cliente; la regla real la aplica la API, que responde 400 y su mensaje se muestra junto al campo.
(function () {
  const api = window.TrackflowInventoryApi;
  const ui = window.TrackflowInventoryUi;
  const auth = window.TrackflowAuth;

  const form = document.querySelector("#exitForm");
  const skuInput = form.elements.sku_id;
  const warehouseInput = form.elements.warehouse;
  const quantityInput = form.elements.quantity;
  const trackingInput = form.elements.tracking_number;
  const trackingField = document.querySelector("#trackingField");
  const quantityWarning = document.querySelector("#quantityWarning");
  const quantityAvailable = document.querySelector("#quantityAvailable");
  const stockPanel = document.querySelector("#stockPanel");
  const formAlert = document.querySelector("#formAlert");
  const submitButton = document.querySelector("#submitButton");

  let skus = [];
  let stock = { status: "idle", sku: null, error: null };
  // Solo cuenta la respuesta de la última consulta de stock (el usuario puede cambiar de SKU deprisa).
  let stockRequest = 0;
  // Tras un 400 de stock insuficiente manda el mensaje de la API: el aviso del cliente se calla
  // hasta que se cambie la cantidad, para no repetir lo mismo dos veces.
  let apiQuantityError = false;

  const exitType = () => form.elements.exit_type.value;

  function available() {
    return stock.status === "ready" && warehouseInput.value ? stock.sku.stock_by_warehouse[warehouseInput.value] ?? 0 : null;
  }

  // ---------------------------------------------------------------- panel de stock

  function renderStockPanel() {
    stockPanel.dataset.status = stock.status;
    if (stock.status === "idle") {
      stockPanel.replaceChildren("Selecciona un SKU para ver su stock disponible.");
    } else if (stock.status === "loading") {
      stockPanel.replaceChildren(ui.el("p", "font-semibold text-cyan-800", "Consultando el stock actual…"));
    } else if (stock.status === "error") {
      const retry = ui.el("button", "mt-3 rounded-lg border border-cyan-300 bg-white px-3 py-1.5 text-sm font-semibold text-cyan-800 hover:bg-cyan-50", "Reintentar");
      retry.type = "button";
      retry.addEventListener("click", () => loadStock(skuInput.value));
      stockPanel.replaceChildren(
        ui.el("p", "rounded-lg border border-red-200 bg-red-50 p-3 text-red-700", `No se pudo consultar el stock. ${stock.error}`),
        retry,
      );
    } else {
      const sku = stock.sku;
      const warehouse = warehouseInput.value || sku.warehouse;
      const units = sku.stock_by_warehouse[warehouse] ?? 0;
      const big = ui.el("p", `mt-1 text-4xl font-black ${ui.stockLevel(units).text}`, ui.formatUnits(units));
      big.id = "availableStock";
      big.dataset.units = String(units);
      const nodes = [
        ui.el("p", "font-mono text-xs font-bold text-slate-900", sku.sku),
        ui.el("p", "font-semibold text-slate-800", sku.name),
        ui.el("p", "mt-4 text-xs font-bold uppercase tracking-wide text-slate-500", `Disponible en ${ui.warehouseName(warehouse)}`),
        big,
        ui.stockBadge(units, { showLevel: true }),
      ];
      for (const [code, otherUnits] of Object.entries(sku.stock_by_warehouse)) {
        if (code !== warehouse && otherUnits !== 0) {
          nodes.push(ui.el("p", "mt-3 text-xs text-slate-500", `En ${ui.warehouseName(code)} hay ${ui.formatUnits(otherUnits)}, que no cuentan para esta salida.`));
        }
      }
      if (units <= 0) {
        nodes.push(ui.el("p", "mt-3 rounded-lg border border-red-200 bg-red-50 p-3 font-semibold text-red-700", `No hay stock de este SKU en ${ui.warehouseName(warehouse)}: no se puede registrar ninguna salida desde este almacén.`));
      }
      stockPanel.replaceChildren(...nodes);
    }
    renderQuantityWarning();
  }

  function renderQuantityAvailable() {
    const units = available();
    quantityAvailable.textContent = units === null
      ? ""
      : `Disponible en ${ui.warehouseName(warehouseInput.value)}: ${ui.formatUnits(units)}`;
    quantityAvailable.className = `mt-1 block text-sm font-semibold ${units === null ? "text-slate-600" : ui.stockLevel(units).text}`;
  }

  function renderQuantityWarning() {
    renderQuantityAvailable();
    const units = available();
    const quantity = ui.positiveInteger(quantityInput.value);
    if (apiQuantityError || units === null || quantity === null || quantity <= units) {
      quantityWarning.hidden = true;
      quantityWarning.textContent = "";
      return;
    }
    quantityWarning.textContent =
      `Atención: quieres sacar ${ui.formatUnits(quantity)}, pero solo hay ${ui.formatUnits(units)} ` +
      `en ${ui.warehouseName(warehouseInput.value)}. Reduce la cantidad: la salida será rechazada.`;
    quantityWarning.hidden = false;
  }

  async function loadStock(skuId) {
    const request = ++stockRequest;
    if (!skuId) {
      stock = { status: "idle", sku: null, error: null };
      renderStockPanel();
      return;
    }
    stock = { status: "loading", sku: null, error: null };
    renderStockPanel();
    try {
      const sku = await api.getSku(skuId);
      if (request !== stockRequest) return;
      skus = skus.map((item) => (item.id === sku.id ? sku : item));
      stock = { status: "ready", sku, error: null };
    } catch (error) {
      if (request !== stockRequest || error instanceof auth.SessionExpiredError) return;
      stock = { status: "error", sku: null, error: error.message };
    }
    renderStockPanel();
  }

  // ---------------------------------------------------------------- formulario

  // Otro SKU, almacén o cantidad: el 400 anterior ya no aplica.
  function clearApiQuantityError() {
    if (!apiQuantityError) return;
    apiQuantityError = false;
    ui.clearFieldError(form, "quantity");
  }

  function onSkuChange() {
    clearApiQuantityError();
    const sku = skus.find((item) => String(item.id) === skuInput.value);
    // El almacén de salida por defecto es el del SKU; se puede cambiar si sale del otro almacén.
    if (sku) warehouseInput.value = sku.warehouse;
    loadStock(skuInput.value);
  }

  function onExitTypeChange() {
    const isDispatch = exitType() === "dispatch";
    // Con clase y no con el atributo hidden: la clase `block` de Tailwind anularía el atributo.
    trackingField.classList.toggle("hidden", !isDispatch);
    trackingInput.disabled = !isDispatch;
    if (!isDispatch) trackingInput.value = "";
  }

  function validate() {
    const errors = {};
    if (!skuInput.value) errors.sku_id = "Elige el SKU que sale.";
    if (!warehouseInput.value) errors.warehouse = "Elige el almacén del que sale la mercancía.";
    if (exitType() === "dispatch" && !trackingInput.value.trim()) {
      errors.tracking_number = "Introduce el número de seguimiento del transportista: es obligatorio en un despacho.";
    }
    if (ui.positiveInteger(quantityInput.value) === null) errors.quantity = "Introduce un número entero de unidades mayor que 0.";
    return errors;
  }

  async function confirmation(stockExit) {
    const what = stockExit.exit_type === "dispatch"
      ? `despacho de ${ui.formatUnits(stockExit.quantity)}, seguimiento ${stockExit.tracking_number}`
      : `pérdida de ${ui.formatUnits(stockExit.quantity)}`;
    const base = `Salida registrada: ${what} de ${stockExit.sku.sku} (${stockExit.sku.name}) desde ${ui.warehouseName(stockExit.warehouse)}.`;
    try {
      const fresh = await api.getSku(stockExit.sku_id);
      skus = skus.map((item) => (item.id === fresh.id ? fresh : item));
      return `${base} Quedan ${ui.formatUnits(fresh.stock_by_warehouse[stockExit.warehouse])} en ${ui.warehouseName(stockExit.warehouse)}.`;
    } catch (error) {
      if (error instanceof auth.SessionExpiredError) throw error;
      return `${base} (No se pudo consultar el stock actualizado: ${error.message})`;
    }
  }

  async function loadSkus() {
    skuInput.disabled = true;
    try {
      skus = await api.listSkus();
      ui.fillSkuSelect(skuInput, skus, ui.queryParam("sku_id"));
      if (skuInput.value) onSkuChange();
      if (!skus.length) ui.showAlert(formAlert, "warning", "No hay SKUs registrados todavía: no se puede registrar ninguna salida.");
    } catch (error) {
      if (error instanceof auth.SessionExpiredError) return;
      ui.showAlert(formAlert, "error", `No se pudo cargar la lista de SKUs. ${error.message}`);
    } finally {
      skuInput.disabled = false;
    }
  }

  skuInput.addEventListener("change", onSkuChange);
  warehouseInput.addEventListener("change", () => {
    clearApiQuantityError();
    renderStockPanel();
  });
  quantityInput.addEventListener("input", () => {
    clearApiQuantityError();
    renderQuantityWarning();
  });
  form.querySelectorAll('input[name="exit_type"]').forEach((radio) => radio.addEventListener("change", onExitTypeChange));

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    ui.clearFieldErrors(form);
    ui.hideAlert(formAlert);

    const errors = validate();
    if (Object.keys(errors).length) {
      ui.showFieldErrors(form, errors);
      ui.showAlert(formAlert, "error", "Revisa los campos marcados.");
      form.elements[Object.keys(errors)[0]].focus?.();
      return;
    }

    const isDispatch = exitType() === "dispatch";
    submitButton.disabled = true;
    submitButton.textContent = "Registrando…";
    try {
      const stockExit = await api.registerExit({
        sku_id: Number(skuInput.value),
        quantity: ui.positiveInteger(quantityInput.value),
        exit_type: exitType(),
        tracking_number: isDispatch ? trackingInput.value.trim() : null,
        warehouse: warehouseInput.value,
      });
      const message = await confirmation(stockExit);
      form.reset();
      apiQuantityError = false;
      onExitTypeChange();
      stockRequest++;
      stock = { status: "idle", sku: null, error: null };
      renderStockPanel();
      ui.showAlert(formAlert, "success", message);
      skuInput.focus();
    } catch (error) {
      if (error instanceof auth.SessionExpiredError) return;
      const unplaced = ui.showFieldErrors(form, error.fieldErrors);
      if (error.kind === "insufficient_stock") {
        apiQuantityError = true;
        // El 400 va junto al campo de cantidad; el panel se actualiza con el stock real de la API.
        ui.showAlert(formAlert, "error", "No se ha registrado la salida: no hay stock suficiente. Revisa la cantidad.");
        quantityInput.focus();
        loadStock(skuInput.value);
      } else {
        ui.showAlert(formAlert, "error", [`No se ha registrado la salida. ${error.message}`, ...unplaced].join(" "));
      }
    } finally {
      submitButton.disabled = false;
      submitButton.textContent = "Registrar salida";
    }
  });

  onExitTypeChange();
  renderStockPanel();
  loadSkus();
})();
