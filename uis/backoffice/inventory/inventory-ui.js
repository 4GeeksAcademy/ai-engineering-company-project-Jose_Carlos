// Utilidades de interfaz compartidas por las páginas de inventario: vocabulario de CONTEXT-9,
// niveles de stock y pequeños helpers del DOM. No hace peticiones (eso es inventory-api.js).
(function () {
  const { WAREHOUSE_NAMES } = window.TrackflowInventoryApi;

  const CATEGORY_LABELS = { fashion: "Moda", electronics: "Electrónica", cosmetics: "Cosmética" };
  const EXIT_TYPE_LABELS = { dispatch: "Despacho a cliente", loss: "Pérdida" };

  // ---------------------------------------------------------------- niveles de stock
  //
  // Umbrales (unidades de un SKU en un almacén):
  //   - 0           → "Sin stock"  (rojo):  no se puede despachar nada.
  //   - 1 a 49      → "Stock bajo" (ámbar): conviene pedir reposición a la marca cliente.
  //   - 50 o más    → "Stock OK"   (verde).
  // 50 unidades cubren aproximadamente una semana de despachos de un SKU con salida habitual en
  // TrackFlow. Es un umbral único para todos los SKUs: si un cliente necesita otro, se ajusta aquí.
  const LOW_STOCK_THRESHOLD = 50;

  const STOCK_LEVELS = {
    out: { label: "Sin stock", icon: "✕", badge: "border-red-200 bg-red-50 text-red-800", text: "text-red-700" },
    low: { label: "Stock bajo", icon: "!", badge: "border-amber-200 bg-amber-50 text-amber-900", text: "text-amber-800" },
    ok: { label: "Stock OK", icon: "✓", badge: "border-emerald-200 bg-emerald-50 text-emerald-800", text: "text-emerald-700" },
  };

  function stockLevel(units) {
    if (units <= 0) return { key: "out", ...STOCK_LEVELS.out };
    if (units < LOW_STOCK_THRESHOLD) return { key: "low", ...STOCK_LEVELS.low };
    return { key: "ok", ...STOCK_LEVELS.ok };
  }

  // ---------------------------------------------------------------- formato

  function warehouseName(code) {
    return WAREHOUSE_NAMES[code] || code;
  }

  function formatUnits(count) {
    const n = Number(count);
    return `${n.toLocaleString("es-ES")} ${n === 1 ? "unidad" : "unidades"}`;
  }

  function formatDateTime(iso) {
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return "—";
    return date.toLocaleString("es-ES", { dateStyle: "medium", timeStyle: "short" });
  }

  /** Texto de una opción del selector de SKU: por nombre, con su código y almacén. */
  function skuOptionLabel(sku) {
    return `${sku.name} — ${sku.sku} (${warehouseName(sku.warehouse)})`;
  }

  // ---------------------------------------------------------------- DOM

  /** Crea un elemento con clases y texto (nunca innerHTML con datos de la API). */
  function el(tag, className = "", text = "") {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== "") node.textContent = text;
    return node;
  }

  /** Etiqueta de color con el stock (o, con showLevel, con el nivel: "Stock bajo"…). */
  function stockBadge(units, { showLevel = false } = {}) {
    const level = stockLevel(units);
    const badge = el("span", `inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 py-1 text-sm font-bold ${level.badge}`);
    badge.dataset.level = level.key;
    badge.append(el("span", "", level.icon), el("span", "", showLevel ? level.label : formatUnits(units)));
    badge.title = level.label;
    return badge;
  }

  const ALERT_STYLES = {
    success: "border-emerald-200 bg-emerald-50 text-emerald-800",
    error: "border-red-200 bg-red-50 text-red-700",
    warning: "border-amber-200 bg-amber-50 text-amber-900",
    info: "border-cyan-200 bg-cyan-50 text-cyan-900",
  };

  function showAlert(element, type, message) {
    element.className = `rounded-xl border p-4 text-sm ${ALERT_STYLES[type]}`;
    element.dataset.type = type;
    element.textContent = message;
    element.hidden = false;
  }

  function hideAlert(element) {
    element.hidden = true;
    element.textContent = "";
    delete element.dataset.type;
  }

  /** Error de un campo: <p data-error-for="campo"> debajo del input, más aria-invalid. */
  function setFieldError(form, field, message) {
    const slot = form.querySelector(`[data-error-for="${field}"]`);
    const input = form.elements[field];
    if (slot) {
      slot.textContent = message;
      slot.hidden = false;
    }
    if (input && input.setAttribute) input.setAttribute("aria-invalid", "true");
    return Boolean(slot);
  }

  function clearFieldError(form, field) {
    const slot = form.querySelector(`[data-error-for="${field}"]`);
    if (slot) {
      slot.textContent = "";
      slot.hidden = true;
    }
    form.elements[field]?.removeAttribute?.("aria-invalid");
  }

  function clearFieldErrors(form) {
    form.querySelectorAll("[data-error-for]").forEach((slot) => {
      slot.textContent = "";
      slot.hidden = true;
    });
    form.querySelectorAll("[aria-invalid]").forEach((input) => input.removeAttribute("aria-invalid"));
  }

  /** Pinta los errores por campo de un InventoryApiError; devuelve los que no tenían sitio. */
  function showFieldErrors(form, fieldErrors) {
    return Object.entries(fieldErrors || {})
      .filter(([field, message]) => !setFieldError(form, field, message))
      .map(([, message]) => message);
  }

  function fillSkuSelect(select, skus, selectedId) {
    select.replaceChildren(el("option", "", "Selecciona un SKU…"));
    select.firstChild.value = "";
    const sorted = [...skus].sort((a, b) => a.name.localeCompare(b.name, "es") || a.sku.localeCompare(b.sku));
    for (const code of Object.keys(WAREHOUSE_NAMES)) {
      const group = el("optgroup");
      group.label = `Almacén ${warehouseName(code)}`;
      for (const sku of sorted.filter((item) => item.warehouse === code)) {
        const option = el("option", "", skuOptionLabel(sku));
        option.value = String(sku.id);
        group.append(option);
      }
      if (group.children.length) select.append(group);
    }
    if (selectedId && skus.some((sku) => String(sku.id) === String(selectedId))) select.value = String(selectedId);
  }

  /** Entero positivo de un input, o null si no lo es. */
  function positiveInteger(value) {
    const text = String(value).trim();
    if (!/^\d+$/.test(text)) return null;
    const n = Number(text);
    return n > 0 && Number.isSafeInteger(n) ? n : null;
  }

  function queryParam(name) {
    return new URLSearchParams(window.location.search).get(name);
  }

  window.TrackflowInventoryUi = {
    CATEGORY_LABELS,
    EXIT_TYPE_LABELS,
    LOW_STOCK_THRESHOLD,
    clearFieldError,
    clearFieldErrors,
    el,
    fillSkuSelect,
    formatDateTime,
    formatUnits,
    hideAlert,
    positiveInteger,
    queryParam,
    setFieldError,
    showAlert,
    showFieldErrors,
    skuOptionLabel,
    stockBadge,
    stockLevel,
    warehouseName,
  };
})();
