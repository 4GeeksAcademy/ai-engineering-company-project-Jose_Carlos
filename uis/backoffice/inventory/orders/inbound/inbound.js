// Recepción de mercancía — POST /inventory/orders/inbound (StockEntry).
(function () {
  const api = window.TrackflowInventoryApi;
  const ui = window.TrackflowInventoryUi;
  const auth = window.TrackflowAuth;

  const form = document.querySelector("#entryForm");
  const skuInput = form.elements.sku_id;
  const warehouseInput = form.elements.warehouse;
  const quantityInput = form.elements.quantity;
  const referenceInput = form.elements.reference;
  const skuHint = document.querySelector("#skuHint");
  const formAlert = document.querySelector("#formAlert");
  const submitButton = document.querySelector("#submitButton");

  let skus = [];

  function selectedSku() {
    return skus.find((sku) => String(sku.id) === skuInput.value) || null;
  }

  function renderHint() {
    const sku = selectedSku();
    if (!sku) {
      skuHint.textContent = "";
      return;
    }
    const warehouse = warehouseInput.value || sku.warehouse;
    const units = sku.stock_by_warehouse[warehouse] ?? 0;
    let text = `Stock actual en ${ui.warehouseName(warehouse)}: ${ui.formatUnits(units)}.`;
    if (warehouse !== sku.warehouse) {
      text += ` Este SKU está registrado en ${ui.warehouseName(sku.warehouse)}: la entrada sumará stock en ${ui.warehouseName(warehouse)}.`;
    }
    skuHint.textContent = text;
  }

  function onSkuChange() {
    const sku = selectedSku();
    // El almacén receptor por defecto es el del SKU; se puede cambiar si llega a otro almacén.
    if (sku) warehouseInput.value = sku.warehouse;
    renderHint();
  }

  function validate() {
    const errors = {};
    if (!skuInput.value) errors.sku_id = "Elige el SKU recibido.";
    if (!warehouseInput.value) errors.warehouse = "Elige el almacén que recibe la mercancía.";
    if (ui.positiveInteger(quantityInput.value) === null) errors.quantity = "Introduce un número entero de unidades mayor que 0.";
    if (!referenceInput.value.trim()) errors.reference = "Indica la referencia de despacho del cliente (p. ej. PO-2024-0098).";
    return errors;
  }

  async function loadSkus() {
    skuInput.disabled = true;
    try {
      skus = await api.listSkus();
      ui.fillSkuSelect(skuInput, skus, ui.queryParam("sku_id"));
      onSkuChange();
      if (!skus.length) ui.showAlert(formAlert, "warning", "No hay SKUs registrados todavía: no se puede registrar ninguna entrada.");
    } catch (error) {
      if (error instanceof auth.SessionExpiredError) return;
      ui.showAlert(formAlert, "error", `No se pudo cargar la lista de SKUs. ${error.message}`);
    } finally {
      skuInput.disabled = false;
    }
  }

  async function confirmation(entry) {
    const base =
      `Entrada registrada: ${ui.formatUnits(entry.quantity)} de ${entry.sku.sku} (${entry.sku.name}) ` +
      `en ${ui.warehouseName(entry.warehouse)}, ref. ${entry.reference}.`;
    try {
      const fresh = await api.getSku(entry.sku_id);
      skus = skus.map((sku) => (sku.id === fresh.id ? fresh : sku));
      return `${base} Stock actual en ${ui.warehouseName(entry.warehouse)}: ${ui.formatUnits(fresh.stock_by_warehouse[entry.warehouse])}.`;
    } catch (error) {
      if (error instanceof auth.SessionExpiredError) throw error;
      return `${base} (No se pudo consultar el stock actualizado: ${error.message})`;
    }
  }

  skuInput.addEventListener("change", onSkuChange);
  warehouseInput.addEventListener("change", renderHint);

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    ui.clearFieldErrors(form);
    ui.hideAlert(formAlert);

    const errors = validate();
    if (Object.keys(errors).length) {
      ui.showFieldErrors(form, errors);
      ui.showAlert(formAlert, "error", "Revisa los campos marcados.");
      form.elements[Object.keys(errors)[0]].focus();
      return;
    }

    submitButton.disabled = true;
    submitButton.textContent = "Registrando…";
    try {
      const entry = await api.registerEntry({
        sku_id: Number(skuInput.value),
        quantity: ui.positiveInteger(quantityInput.value),
        reference: referenceInput.value.trim(),
        warehouse: warehouseInput.value,
      });
      const message = await confirmation(entry);
      form.reset();
      renderHint();
      ui.showAlert(formAlert, "success", message);
      skuInput.focus();
    } catch (error) {
      if (error instanceof auth.SessionExpiredError) return;
      const unplaced = ui.showFieldErrors(form, error.fieldErrors);
      ui.showAlert(formAlert, "error", [`No se ha registrado la entrada. ${error.message}`, ...unplaced].join(" "));
    } finally {
      submitButton.disabled = false;
      submitButton.textContent = "Registrar entrada";
    }
  });

  loadSkus();
})();
