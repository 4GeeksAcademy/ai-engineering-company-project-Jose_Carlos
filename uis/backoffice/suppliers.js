function getDefaultApiBaseUrl() {
  if (window.location.hostname.endsWith(".app.github.dev")) {
    const apiHostname = window.location.hostname.replace(
      /-\d+\.app\.github\.dev$/,
      "-8000.app.github.dev",
    );
    return `${window.location.protocol}//${apiHostname}`;
  }

  return "http://localhost:8000";
}

// Servido por FastAPI en /backoffice → misma origen; servido aparte (p. ej. :5500) → API_BASE.
const isSameOriginBackoffice = window.location.pathname.startsWith("/backoffice");
const API_BASE = window.SUPPLIERS_API_BASE_URL || getDefaultApiBaseUrl();
const SUPPLIERS_BASE = isSameOriginBackoffice ? "/suppliers" : `${API_BASE}/suppliers`;

// Valores exactos de audit/CONTEXTS/CONTEXT-7-trackflow.es.md
const VALID_CATEGORIES = [
  "carrier_last_mile",
  "carrier_international",
  "warehouse_supplies",
  "packaging_materials",
  "reverse_logistics",
  "fleet_maintenance",
  "it_and_wms_software",
  "cleaning_and_facilities",
];

const CATEGORY_LABELS = {
  carrier_last_mile: "Carrier última milla",
  carrier_international: "Carrier internacional",
  warehouse_supplies: "Suministros de almacén",
  packaging_materials: "Material de embalaje",
  reverse_logistics: "Logística inversa",
  fleet_maintenance: "Mantenimiento de flota",
  it_and_wms_software: "Software IT / WMS",
  cleaning_and_facilities: "Limpieza e instalaciones",
};

const CURRENCY_BY_COUNTRY = { USA: "USD", Spain: "EUR" };

const STATUS_LABELS = { active: "Activo", suspended: "Suspendido" };

const countryFilter = document.querySelector("#countryFilter");
const categoryFilter = document.querySelector("#categoryFilter");
const resultsCount = document.querySelector("#resultsCount");
const listMessage = document.querySelector("#listMessage");
const listLoading = document.querySelector("#listLoading");
const tableBody = document.querySelector("#suppliersTableBody");

const createForm = document.querySelector("#createForm");
const countryInput = document.querySelector("#countryInput");
const currencyInput = document.querySelector("#currencyInput");
const categoriesInput = document.querySelector("#categoriesInput");
const createMessage = document.querySelector("#createMessage");
const createButton = document.querySelector("#createButton");

let suppliers = [];

// =========================================================
// API
// =========================================================

// Convierte el cuerpo de error de FastAPI en un texto legible.
// 422 → detail es una lista [{loc, msg}]; 404 → detail es un string.
function formatApiError(body, status) {
  const detail = body && body.detail;

  if (Array.isArray(detail)) {
    return detail
      .map((error) => {
        const field = (error.loc || []).filter((part) => part !== "body").join(".");
        const message = String(error.msg || "").replace(/^Value error, /, "");
        return field ? `${field}: ${message}` : message;
      })
      .join(" · ");
  }

  if (typeof detail === "string") {
    return detail;
  }

  return `Error ${status} en la API.`;
}

async function apiRequest(url, options = {}) {
  let response;
  try {
    response = await fetch(url, {
      ...options,
      headers: options.body ? { "Content-Type": "application/json" } : undefined,
    });
  } catch {
    throw new Error("No se pudo conectar con la API. Comprueba que el servidor está arrancado.");
  }

  const body = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(formatApiError(body, response.status));
  }
  return body;
}

function fetchSuppliers(country, category) {
  const params = new URLSearchParams();
  if (country) params.set("country", country);
  if (category) params.set("category", category);
  const query = params.toString();
  return apiRequest(query ? `${SUPPLIERS_BASE}?${query}` : SUPPLIERS_BASE);
}

function createSupplier(data) {
  return apiRequest(SUPPLIERS_BASE, { method: "POST", body: JSON.stringify(data) });
}

function updateRate(id, rate) {
  return apiRequest(`${SUPPLIERS_BASE}/${id}/rate`, {
    method: "PATCH",
    body: JSON.stringify({ rate_per_shipment: rate }),
  });
}

function updateStatus(id, status) {
  return apiRequest(`${SUPPLIERS_BASE}/${id}/status`, {
    method: "PATCH",
    body: JSON.stringify({ status }),
  });
}

// =========================================================
// UI
// =========================================================

function showMessage(element, type, message) {
  const isError = type === "error";
  element.textContent = message;
  element.className = `${element.id === "createMessage" ? "mb-4" : "mt-5"} rounded-xl border p-4 text-sm ${
    isError
      ? "border-red-200 bg-red-50 font-semibold text-red-800"
      : "border-cyan-200 bg-cyan-50 text-cyan-900"
  }`;
}

function hideMessage(element) {
  element.classList.add("hidden");
  element.textContent = "";
}

function setLoading(loading) {
  listLoading.classList.toggle("hidden", !loading);
  listLoading.classList.toggle("flex", loading);
}

function formatMoney(amount, currency) {
  return new Intl.NumberFormat("es-ES", { style: "currency", currency }).format(amount);
}

function formatDate(isoString) {
  return new Intl.DateTimeFormat("es-ES", { dateStyle: "short", timeStyle: "short" }).format(
    new Date(isoString),
  );
}

function createElement(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function statusBadge(status) {
  const colors =
    status === "active"
      ? "bg-green-100 text-green-800 ring-green-200"
      : "bg-amber-100 text-amber-800 ring-amber-200";
  return createElement(
    "span",
    `inline-flex rounded-full px-3 py-1 text-xs font-bold ring-1 ${colors}`,
    STATUS_LABELS[status] || status,
  );
}

function renderSupplierCell(supplier) {
  const cell = createElement("td", "py-4 pr-4 align-top");
  cell.append(createElement("p", "font-bold text-slate-900", supplier.name));

  const details = [supplier.country, supplier.service_zone].filter(Boolean).join(" · ");
  cell.append(createElement("p", "text-xs text-slate-500", details));

  if (supplier.contact_email) {
    cell.append(createElement("p", "text-xs text-slate-500", supplier.contact_email));
  }
  if (supplier.notes) {
    cell.append(createElement("p", "mt-1 max-w-xs text-xs italic text-slate-500", supplier.notes));
  }
  return cell;
}

function renderCategoriesCell(supplier) {
  const cell = createElement("td", "py-4 pr-4 align-top");
  const list = createElement("div", "flex max-w-xs flex-wrap gap-1");
  supplier.categories.forEach((category) => {
    const chip = createElement(
      "span",
      "rounded-full bg-cyan-100 px-2 py-0.5 text-xs font-semibold text-cyan-800",
      CATEGORY_LABELS[category] || category,
    );
    chip.title = category;
    list.append(chip);
  });
  cell.append(list);
  return cell;
}

function renderRateCell(supplier) {
  const cell = createElement("td", "py-4 pr-4 align-top");
  cell.append(
    createElement("p", "font-bold text-slate-900", formatMoney(supplier.rate_per_shipment, supplier.currency)),
  );

  // Editor de tarifa en línea
  const form = createElement("form", "mt-2 flex items-center gap-2");
  form.noValidate = true;

  const input = createElement(
    "input",
    "w-24 rounded-lg border border-cyan-200 px-2 py-1 text-sm focus:border-cyan-500 focus:outline-none focus:ring-2 focus:ring-cyan-200",
  );
  input.type = "number";
  input.min = "0.01";
  input.step = "0.01";
  input.value = supplier.rate_per_shipment;
  input.setAttribute("aria-label", `Nueva tarifa para ${supplier.name}`);

  const button = createElement(
    "button",
    "rounded-lg border border-cyan-300 bg-white px-2 py-1 text-xs font-bold text-cyan-800 transition hover:bg-cyan-50 disabled:cursor-not-allowed disabled:text-slate-400",
    "Guardar",
  );
  button.type = "submit";

  const error = createElement("p", "mt-1 hidden text-xs font-semibold text-red-700");
  error.setAttribute("role", "alert");

  form.append(input, button);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    error.classList.add("hidden");

    const rate = Number(input.value);
    if (input.value.trim() === "" || !Number.isFinite(rate) || rate <= 0) {
      error.textContent = "La tarifa debe ser mayor que 0.";
      error.classList.remove("hidden");
      input.focus();
      return;
    }

    button.disabled = true;
    button.textContent = "Guardando...";
    try {
      replaceSupplier(await updateRate(supplier.id, rate));
    } catch (requestError) {
      error.textContent = requestError.message;
      error.classList.remove("hidden");
      button.disabled = false;
      button.textContent = "Guardar";
    }
  });

  cell.append(form, error);
  return cell;
}

function renderActionsCell(supplier) {
  const cell = createElement("td", "py-4 align-top text-right");
  const isActive = supplier.status === "active";
  const nextStatus = isActive ? "suspended" : "active";

  const button = createElement(
    "button",
    `whitespace-nowrap rounded-lg border px-3 py-2 text-xs font-bold transition disabled:cursor-not-allowed disabled:opacity-60 ${
      isActive
        ? "border-amber-300 bg-white text-amber-800 hover:bg-amber-50"
        : "border-green-300 bg-white text-green-800 hover:bg-green-50"
    }`,
    isActive ? "Suspender" : "Reactivar",
  );
  button.type = "button";

  const error = createElement("p", "mt-1 hidden text-xs font-semibold text-red-700");
  error.setAttribute("role", "alert");

  button.addEventListener("click", async () => {
    button.disabled = true;
    error.classList.add("hidden");
    try {
      replaceSupplier(await updateStatus(supplier.id, nextStatus));
    } catch (requestError) {
      error.textContent = requestError.message;
      error.classList.remove("hidden");
      button.disabled = false;
    }
  });

  cell.append(button, error);
  return cell;
}

function renderTable(list) {
  tableBody.replaceChildren();
  resultsCount.textContent = `${list.length} ${list.length === 1 ? "proveedor" : "proveedores"}`;

  if (list.length === 0) {
    const row = createElement("tr");
    const cell = createElement("td", "py-6 text-center text-slate-600", "No hay proveedores con estos filtros.");
    cell.colSpan = 6;
    row.append(cell);
    tableBody.append(row);
    return;
  }

  list.forEach((supplier) => {
    const row = createElement("tr");
    row.dataset.id = supplier.id;

    const statusCell = createElement("td", "py-4 pr-4 align-top");
    statusCell.append(statusBadge(supplier.status));

    const updatedCell = createElement(
      "td",
      "whitespace-nowrap py-4 pr-4 align-top text-xs text-slate-500",
      formatDate(supplier.updated_at),
    );

    row.append(
      renderSupplierCell(supplier),
      renderCategoriesCell(supplier),
      renderRateCell(supplier),
      statusCell,
      updatedCell,
      renderActionsCell(supplier),
    );
    tableBody.append(row);
  });
}

// Sustituye un proveedor en la lista local y vuelve a pintar (sin recargar la página)
function replaceSupplier(updated) {
  suppliers = suppliers.map((supplier) => (supplier.id === updated.id ? updated : supplier));
  renderTable(suppliers);
}

async function loadSuppliers() {
  hideMessage(listMessage);
  setLoading(true);
  try {
    suppliers = await fetchSuppliers(countryFilter.value, categoryFilter.value);
    renderTable(suppliers);
  } catch (error) {
    tableBody.replaceChildren();
    resultsCount.textContent = "";
    showMessage(listMessage, "error", error.message);
  } finally {
    setLoading(false);
  }
}

// =========================================================
// FORMULARIO DE ALTA
// =========================================================

function renderCategoryOptions() {
  VALID_CATEGORIES.forEach((category) => {
    categoryFilter.append(new Option(CATEGORY_LABELS[category], category));

    const label = createElement(
      "label",
      "flex items-center gap-2 rounded-lg border border-cyan-100 px-3 py-2 text-sm text-slate-700 hover:bg-cyan-50",
    );
    const checkbox = createElement("input", "h-4 w-4 accent-cyan-700");
    checkbox.type = "checkbox";
    checkbox.name = "categories";
    checkbox.value = category;
    label.append(checkbox, document.createTextNode(CATEGORY_LABELS[category]));
    categoriesInput.append(label);
  });
}

function optionalValue(form, name) {
  const value = form.elements[name].value.trim();
  return value === "" ? null : value;
}

// Validación en cliente; devuelve la lista de errores
function validateCreateForm(data) {
  const errors = [];
  if (!data.name) errors.push("El nombre es obligatorio.");
  if (!CURRENCY_BY_COUNTRY[data.country]) errors.push("Selecciona un país.");
  if (data.categories.length === 0) errors.push("Selecciona al menos una categoría.");
  if (!Number.isFinite(data.rate_per_shipment) || data.rate_per_shipment <= 0) {
    errors.push("La tarifa debe ser mayor que 0.");
  }
  return errors;
}

countryInput.addEventListener("change", () => {
  currencyInput.value = CURRENCY_BY_COUNTRY[countryInput.value] || "";
});

createForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  hideMessage(createMessage);

  const rateText = createForm.elements.rate_per_shipment.value.trim();
  const data = {
    name: createForm.elements.name.value.trim(),
    country: countryInput.value,
    categories: [...createForm.querySelectorAll('input[name="categories"]:checked')].map(
      (checkbox) => checkbox.value,
    ),
    rate_per_shipment: rateText === "" ? NaN : Number(rateText),
    currency: CURRENCY_BY_COUNTRY[countryInput.value],
    status: createForm.elements.status.value,
    service_zone: optionalValue(createForm, "service_zone"),
    contact_email: optionalValue(createForm, "contact_email"),
    notes: optionalValue(createForm, "notes"),
  };

  const errors = validateCreateForm(data);
  if (errors.length > 0) {
    showMessage(createMessage, "error", errors.join(" "));
    return;
  }

  createButton.disabled = true;
  createButton.textContent = "Registrando...";
  try {
    const created = await createSupplier(data);
    createForm.reset();
    currencyInput.value = "";
    showMessage(createMessage, "success", `Proveedor "${created.name}" registrado con id ${created.id}.`);
    await loadSuppliers();
  } catch (error) {
    showMessage(createMessage, "error", error.message);
  } finally {
    createButton.disabled = false;
    createButton.textContent = "Registrar proveedor";
  }
});

countryFilter.addEventListener("change", loadSuppliers);
categoryFilter.addEventListener("change", loadSuppliers);

renderCategoryOptions();
loadSuppliers();
