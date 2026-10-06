// Base común del gestor de incidencias (incidents.html e incident-new.html):
// valores del modelo, textos en español e inglés, y llamadas a /api/incidents.
// TrackFlow opera en inglés (Los Ángeles) y en español (Zaragoza).
(function () {
  const LANG_KEY = "trackflow.lang";
  const API_PATH = "/api/incidents";

  // Valores exactos de audit/CONTEXTS/CONTEXT-8-trackflow.es.md
  const STATUSES = ["open", "in_progress", "resolved", "discarded"];
  const ORIGINS = ["customer", "branch", "internal"];
  const BRANCHES = ["central", "la_warehouse", "la_office", "zaragoza_warehouse", "zaragoza_office"];
  const CATEGORIES = [
    "lost_parcel",
    "delivery_failure",
    "inventory_discrepancy",
    "carrier_issue",
    "returns_issue",
    "warehouse_incident",
    "system_failure",
    "client_complaint",
    "other",
  ];
  // Categorías con impacto directo en el SLA con clientes.
  const SLA_CATEGORIES = ["lost_parcel", "carrier_issue"];

  // Ciclo de vida: resolved y discarded son finales.
  const STATUS_TRANSITIONS = {
    open: ["in_progress", "discarded"],
    in_progress: ["resolved", "discarded"],
    resolved: [],
    discarded: [],
  };

  const TITLE_MAX_LENGTH = 120;
  const DESCRIPTION_MAX_LENGTH = 5000;

  const TEXTS = {
    es: {
      "nav.analyzer": "Incidentes",
      "nav.suppliers": "Proveedores",
      "nav.manager": "Gestor de incidencias",
      "nav.new": "Registrar incidencia",
      "nav.logout": "Cerrar sesión",
      "nav.switchLang": "English",

      "status.open": "Abierta",
      "status.in_progress": "En curso",
      "status.resolved": "Resuelta",
      "status.discarded": "Descartada",
      "origin.customer": "Cliente",
      "origin.branch": "Sede",
      "origin.internal": "Interno",
      "originHint.customer": "Reportada por una empresa cliente o un consumidor final",
      "originHint.branch": "Detectada por personal de almacén u oficina",
      "originHint.internal": "Detectada por tecnología, dirección u operaciones",
      "branch.central": "Central",
      "branch.la_warehouse": "Los Ángeles — Almacén",
      "branch.la_office": "Los Ángeles — Oficina",
      "branch.zaragoza_warehouse": "Zaragoza — Almacén",
      "branch.zaragoza_office": "Zaragoza — Oficina",
      "category.lost_parcel": "Paquete perdido",
      "category.delivery_failure": "Fallo de entrega",
      "category.inventory_discrepancy": "Discrepancia de inventario",
      "category.carrier_issue": "Problema de carrier",
      "category.returns_issue": "Problema de devolución",
      "category.warehouse_incident": "Incidente de almacén",
      "category.system_failure": "Fallo de sistema",
      "category.client_complaint": "Queja de cliente",
      "category.other": "Otra",
      "categoryHint.lost_parcel": "Paquete extraviado en tránsito o en almacén.",
      "categoryHint.delivery_failure": "Intento fallido, dirección incorrecta o cliente ausente no gestionado.",
      "categoryHint.inventory_discrepancy": "Diferencia entre el stock registrado y el stock físico.",
      "categoryHint.carrier_issue": "Problema imputable a un carrier: retraso, daño o incumplimiento de SLA.",
      "categoryHint.returns_issue": "Problema en el proceso de devolución o logística inversa.",
      "categoryHint.warehouse_incident": "Daño de mercancía, accidente o fallo de equipamiento en almacén.",
      "categoryHint.system_failure": "Fallo en WMS, integraciones o API de carrier.",
      "categoryHint.client_complaint": "Queja de una empresa cliente sobre el servicio de TrackFlow.",
      "categoryHint.other": "Cualquier incidencia que no encaje en las categorías anteriores.",

      "field.title": "Título",
      "field.description": "Descripción",
      "field.category": "Categoría",
      "field.status": "Estado",
      "field.origin": "Origen",
      "field.branch": "Sede",
      "common.all": "Todos",
      "common.allFem": "Todas",
      "common.select": "Selecciona...",
      "common.retry": "Reintentar",
      "common.loading": "Cargando...",
      "common.sla": "SLA",

      "manager.eyebrow": "Operaciones",
      "manager.title": "Gestor de incidencias",
      "manager.intro": "Todas las incidencias de Los Ángeles y Zaragoza en un único registro: estado, origen y sede.",
      "manager.newButton": "Registrar incidencia",

      "summary.title": "Resumen",
      "summary.total": "Incidencias registradas",
      "summary.active": "Abiertas o en curso",
      "summary.sla": "Paquetes perdidos y problemas de carrier (SLA)",
      "summary.filterBy": "Filtrar el listado por {label}",
      "summary.byStatus": "Por estado",
      "summary.byCategory": "Por categoría",
      "summary.byOrigin": "Por origen",
      "summary.byBranch": "Por sede",
      "summary.loading": "Cargando resumen...",
      "summary.error": "No se pudo cargar el resumen. El resto de la página sigue disponible.",

      "duplicates.title": "Posibles incidencias duplicadas",
      "duplicates.intro": "Incidencias abiertas o en curso que describen un problema muy parecido.",
      "duplicates.loading": "Buscando incidencias repetidas...",
      "duplicates.error": "No se pudo comprobar si hay incidencias repetidas.",
      "duplicates.empty": "No hay incidencias activas repetidas.",
      "duplicates.count": "{n} incidencias",
      "duplicates.view": "Ver en el listado",

      "list.title": "Incidencias",
      "list.count.one": "1 incidencia",
      "list.count.many": "{n} incidencias",
      "list.searchLabel": "Buscar por significado",
      "list.searchPlaceholder": "Ej.: el paquete llegó roto",
      "list.searchButton": "Buscar",
      "list.searchClear": "Quitar búsqueda",
      "list.searchInfo": "Resultados más parecidos a «{q}», aunque estén redactados de otra forma.",
      "list.searchDegraded": "La búsqueda funciona ahora en modo básico: solo encuentra incidencias con palabras parecidas.",
      "list.loading": "Cargando incidencias...",
      "list.error": "No se pudieron cargar las incidencias.",
      "list.searchError": "La búsqueda no está disponible ahora mismo. Puedes seguir usando los filtros.",
      "list.empty": "Todavía no hay incidencias registradas.",
      "list.emptyFiltered": "No hay incidencias que coincidan con los filtros aplicados.",
      "list.emptySearch": "Ninguna incidencia se parece a lo que has buscado. Prueba con otras palabras.",
      "list.colIncident": "Incidencia",
      "list.colActions": "Acciones",
      "list.match": "Coincidencia {n} %",
      "list.changeStatus": "Cambiar el estado de la incidencia {id}",
      "list.finalStatus": "Estado final",
      "list.statusUpdated": "Incidencia #{id}: estado cambiado a «{status}».",
      "list.statusFailed": "No se pudo cambiar el estado de la incidencia #{id}. Se ha restaurado el estado anterior.",
      "list.similar": "Ver similares",
      "list.similarHide": "Ocultar similares",
      "list.similarTitle": "Casos parecidos",
      "list.similarLoading": "Buscando casos parecidos...",
      "list.similarEmpty": "No hay otras incidencias parecidas.",
      "list.similarError": "No se pudieron buscar casos parecidos.",

      "form.eyebrow": "Nuevo reporte",
      "form.title": "Registrar incidencia",
      "form.intro": "Describe lo ocurrido. Los campos con * son obligatorios.",
      "form.titlePlaceholder": "Resumen breve de lo ocurrido",
      "form.descriptionPlaceholder": "Qué ha pasado, dónde y a quién afecta",
      "form.branchHint": "Usa «Central» si no corresponde a una sede concreta.",
      "form.branchHighlight": "Estás reportando desde una sede: indica cuál.",
      "form.submit": "Registrar incidencia",
      "form.submitting": "Registrando...",
      "form.success": "Incidencia #{id} registrada correctamente.",
      "form.successLink": "Ver el listado",
      "form.reviewErrors": "Revisa los campos marcados antes de enviar.",

      "assist.title": "Antes de registrar",
      "assist.intro": "Mientras escribes, buscamos incidencias parecidas ya registradas.",
      "assist.loading": "Buscando incidencias parecidas...",
      "assist.empty": "No hemos encontrado incidencias parecidas.",
      "assist.unavailable": "Ahora no podemos comprobar si ya existe una incidencia parecida. Puedes registrarla igualmente.",
      "assist.similar": "Incidencias parecidas",
      "assist.duplicateWarning": "Puede que esta incidencia ya esté registrada y siga activa. Compruébalo antes de enviar.",
      "assist.duplicate": "Posible duplicado",
      "assist.suggested": "Categoría sugerida",
      "assist.useCategory": "Usar «{category}»",
      "assist.confidence": "{n} % de las incidencias parecidas",

      "error.required.title": "Escribe un título.",
      "error.required.description": "Escribe una descripción.",
      "error.required.category": "Selecciona una categoría.",
      "error.required.origin": "Selecciona el origen.",
      "error.required.branch": "Selecciona una sede.",
      "error.required.status": "Selecciona un estado.",
      "error.too_long.title": "El título no puede superar los 120 caracteres.",
      "error.too_long.description": "La descripción es demasiado larga.",
      "error.invalid_value": "El valor seleccionado no es válido. Elige una de las opciones.",
      "error.invalid_type": "El valor de este campo no es válido.",
      "error.invalid_transition": "Ese cambio de estado no está permitido para esta incidencia.",
      "error.field": "Revisa este campo.",
      "error.network": "No se pudo conectar con el servidor. Comprueba tu conexión e inténtalo de nuevo.",
      "error.server": "Ha ocurrido un problema en el servidor. Inténtalo de nuevo en unos minutos.",
      "error.not_found": "Esta incidencia ya no existe. Actualiza el listado.",
      "error.generic": "No se pudo completar la operación. Inténtalo de nuevo.",
    },
    en: {
      "nav.analyzer": "CSV analyzer",
      "nav.suppliers": "Suppliers",
      "nav.manager": "Incident manager",
      "nav.new": "Report incident",
      "nav.logout": "Log out",
      "nav.switchLang": "Español",

      "status.open": "Open",
      "status.in_progress": "In progress",
      "status.resolved": "Resolved",
      "status.discarded": "Discarded",
      "origin.customer": "Customer",
      "origin.branch": "Site",
      "origin.internal": "Internal",
      "originHint.customer": "Reported by a client company or an end consumer",
      "originHint.branch": "Detected by warehouse or office staff",
      "originHint.internal": "Detected by technology, management or operations",
      "branch.central": "Central",
      "branch.la_warehouse": "Los Angeles — Warehouse",
      "branch.la_office": "Los Angeles — Office",
      "branch.zaragoza_warehouse": "Zaragoza — Warehouse",
      "branch.zaragoza_office": "Zaragoza — Office",
      "category.lost_parcel": "Lost parcel",
      "category.delivery_failure": "Delivery failure",
      "category.inventory_discrepancy": "Inventory discrepancy",
      "category.carrier_issue": "Carrier issue",
      "category.returns_issue": "Returns issue",
      "category.warehouse_incident": "Warehouse incident",
      "category.system_failure": "System failure",
      "category.client_complaint": "Client complaint",
      "category.other": "Other",
      "categoryHint.lost_parcel": "Parcel lost in transit or in the warehouse.",
      "categoryHint.delivery_failure": "Failed attempt, wrong address or unmanaged absent customer.",
      "categoryHint.inventory_discrepancy": "Difference between recorded stock and physical stock.",
      "categoryHint.carrier_issue": "Problem attributable to a carrier: delay, damage or SLA breach.",
      "categoryHint.returns_issue": "Problem in the returns or reverse logistics process.",
      "categoryHint.warehouse_incident": "Damaged goods, accident or equipment failure in the warehouse.",
      "categoryHint.system_failure": "Failure in the WMS, integrations or a carrier API.",
      "categoryHint.client_complaint": "Complaint from a client company about TrackFlow's service.",
      "categoryHint.other": "Any incident that does not fit the categories above.",

      "field.title": "Title",
      "field.description": "Description",
      "field.category": "Category",
      "field.status": "Status",
      "field.origin": "Origin",
      "field.branch": "Site",
      "common.all": "All",
      "common.allFem": "All",
      "common.select": "Select...",
      "common.retry": "Retry",
      "common.loading": "Loading...",
      "common.sla": "SLA",

      "manager.eyebrow": "Operations",
      "manager.title": "Incident manager",
      "manager.intro": "Every incident from Los Angeles and Zaragoza in a single log: status, origin and site.",
      "manager.newButton": "Report incident",

      "summary.title": "Summary",
      "summary.total": "Incidents logged",
      "summary.active": "Open or in progress",
      "summary.sla": "Lost parcels and carrier issues (SLA)",
      "summary.filterBy": "Filter the list by {label}",
      "summary.byStatus": "By status",
      "summary.byCategory": "By category",
      "summary.byOrigin": "By origin",
      "summary.byBranch": "By site",
      "summary.loading": "Loading summary...",
      "summary.error": "The summary could not be loaded. The rest of the page is still available.",

      "duplicates.title": "Possible duplicate incidents",
      "duplicates.intro": "Open or in-progress incidents that describe a very similar problem.",
      "duplicates.loading": "Looking for repeated incidents...",
      "duplicates.error": "Could not check for repeated incidents.",
      "duplicates.empty": "There are no repeated active incidents.",
      "duplicates.count": "{n} incidents",
      "duplicates.view": "View in the list",

      "list.title": "Incidents",
      "list.count.one": "1 incident",
      "list.count.many": "{n} incidents",
      "list.searchLabel": "Search by meaning",
      "list.searchPlaceholder": "E.g. the parcel arrived broken",
      "list.searchButton": "Search",
      "list.searchClear": "Clear search",
      "list.searchInfo": "Closest results to “{q}”, even if they are worded differently.",
      "list.searchDegraded": "Search is running in basic mode: it only finds incidents with similar words.",
      "list.loading": "Loading incidents...",
      "list.error": "The incidents could not be loaded.",
      "list.searchError": "Search is not available right now. You can keep using the filters.",
      "list.empty": "No incidents have been logged yet.",
      "list.emptyFiltered": "No incidents match the selected filters.",
      "list.emptySearch": "No incident looks like your search. Try different words.",
      "list.colIncident": "Incident",
      "list.colActions": "Actions",
      "list.match": "{n}% match",
      "list.changeStatus": "Change the status of incident {id}",
      "list.finalStatus": "Final status",
      "list.statusUpdated": "Incident #{id}: status changed to “{status}”.",
      "list.statusFailed": "The status of incident #{id} could not be changed. The previous status has been restored.",
      "list.similar": "View similar",
      "list.similarHide": "Hide similar",
      "list.similarTitle": "Similar cases",
      "list.similarLoading": "Looking for similar cases...",
      "list.similarEmpty": "There are no other similar incidents.",
      "list.similarError": "Similar cases could not be loaded.",

      "form.eyebrow": "New report",
      "form.title": "Report incident",
      "form.intro": "Describe what happened. Fields marked with * are required.",
      "form.titlePlaceholder": "Short summary of what happened",
      "form.descriptionPlaceholder": "What happened, where and who is affected",
      "form.branchHint": "Use “Central” if it does not belong to a specific site.",
      "form.branchHighlight": "You are reporting from a site: tell us which one.",
      "form.submit": "Report incident",
      "form.submitting": "Saving...",
      "form.success": "Incident #{id} logged successfully.",
      "form.successLink": "View the list",
      "form.reviewErrors": "Check the highlighted fields before sending.",

      "assist.title": "Before you send",
      "assist.intro": "As you type, we look for similar incidents that are already logged.",
      "assist.loading": "Looking for similar incidents...",
      "assist.empty": "We found no similar incidents.",
      "assist.unavailable": "We cannot check for similar incidents right now. You can still log this one.",
      "assist.similar": "Similar incidents",
      "assist.duplicateWarning": "This incident may already be logged and still active. Check before sending.",
      "assist.duplicate": "Possible duplicate",
      "assist.suggested": "Suggested category",
      "assist.useCategory": "Use “{category}”",
      "assist.confidence": "{n}% of similar incidents",

      "error.required.title": "Enter a title.",
      "error.required.description": "Enter a description.",
      "error.required.category": "Select a category.",
      "error.required.origin": "Select the origin.",
      "error.required.branch": "Select a site.",
      "error.required.status": "Select a status.",
      "error.too_long.title": "The title cannot be longer than 120 characters.",
      "error.too_long.description": "The description is too long.",
      "error.invalid_value": "The selected value is not valid. Choose one of the options.",
      "error.invalid_type": "The value of this field is not valid.",
      "error.invalid_transition": "That status change is not allowed for this incident.",
      "error.field": "Check this field.",
      "error.network": "Could not reach the server. Check your connection and try again.",
      "error.server": "Something went wrong on the server. Try again in a few minutes.",
      "error.not_found": "This incident no longer exists. Refresh the list.",
      "error.generic": "The operation could not be completed. Try again.",
    },
  };

  // =========================================================
  // IDIOMA
  // =========================================================

  function readLang() {
    try {
      const saved = window.localStorage.getItem(LANG_KEY);
      if (saved === "es" || saved === "en") return saved;
    } catch {
      // Sin localStorage: se usa el idioma del navegador.
    }
    return (navigator.language || "es").toLowerCase().startsWith("en") ? "en" : "es";
  }

  let lang = readLang();

  function t(key, params = {}) {
    const text = TEXTS[lang][key] ?? TEXTS.es[key] ?? key;
    return text.replace(/\{(\w+)\}/g, (match, name) => (name in params ? String(params[name]) : match));
  }

  function has(key) {
    return key in TEXTS[lang];
  }

  // Traduce los elementos estáticos marcados con data-i18n / data-i18n-placeholder.
  function applyI18n(root = document) {
    document.documentElement.lang = lang;
    root.querySelectorAll("[data-i18n]").forEach((element) => {
      element.textContent = t(element.dataset.i18n);
    });
    root.querySelectorAll("[data-i18n-placeholder]").forEach((element) => {
      element.placeholder = t(element.dataset.i18nPlaceholder);
    });
  }

  function setLang(next) {
    lang = next;
    try {
      window.localStorage.setItem(LANG_KEY, next);
    } catch {
      // El cambio vale solo para esta visita.
    }
    applyI18n();
    document.dispatchEvent(new CustomEvent("trackflow:langchange"));
  }

  document.addEventListener("click", (event) => {
    if (event.target.closest("[data-lang-toggle]")) setLang(lang === "es" ? "en" : "es");
  });

  // =========================================================
  // API
  // =========================================================

  // kind: "network" | "server" | "not_found" | "validation" | "unavailable"
  class ApiError extends Error {
    constructor(kind, status, errors) {
      super(kind);
      this.kind = kind;
      this.status = status;
      this.errors = errors;
    }
  }

  function errorKind(status) {
    if (status === 404) return "not_found";
    if (status === 400 || status === 422) return "validation";
    return "server";
  }

  async function request(path, options = {}) {
    let response;
    try {
      response = await TrackflowAuth.authFetch(TrackflowAuth.apiUrl(`${API_PATH}${path}`), {
        ...options,
        headers: options.body ? { "Content-Type": "application/json" } : undefined,
      });
    } catch (error) {
      // Sesión caducada: authFetch ya está redirigiendo al login.
      if (error instanceof TrackflowAuth.SessionExpiredError) throw error;
      throw new ApiError("network", 0, []);
    }

    const body = await response.json().catch(() => null);
    if (!response.ok) {
      const errors = body && Array.isArray(body.errors) ? body.errors : [];
      throw new ApiError(errorKind(response.status), response.status, errors);
    }
    if (body === null) {
      // Respuesta correcta pero ilegible: se trata como un fallo del servidor para que
      // quien llama no trabaje con `null`.
      throw new ApiError("server", response.status, []);
    }
    return body;
  }

  function query(params) {
    const search = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value) search.set(key, value);
    });
    const text = search.toString();
    return text ? `?${text}` : "";
  }

  const api = {
    list: (filters) => request(query(filters)),
    search: (q, filters) => request(`/search${query({ q, ...filters })}`),
    summary: () => request("/summary"),
    duplicates: () => request("/duplicates"),
    semanticStatus: () => request("/semantic-status"),
    similar: (id) => request(`/${id}/similar`),
    create: (data) => request("", { method: "POST", body: JSON.stringify(data) }),
    suggest: (draft) => request("/suggest", { method: "POST", body: JSON.stringify(draft) }),
    updateStatus: (id, status) =>
      request(`/${id}/status`, { method: "PATCH", body: JSON.stringify({ status }) }),
  };

  // =========================================================
  // MENSAJES DE ERROR
  // =========================================================
  // Nunca se muestra el texto del servidor: el mensaje se elige aquí, en el idioma
  // del usuario, a partir del campo y del código del error.

  function fieldErrorMessage(error) {
    const specific = `error.${error.code}.${error.field}`;
    if (has(specific)) return t(specific);
    const general = `error.${error.code}`;
    return has(general) ? t(general) : t("error.field");
  }

  function errorMessage(error) {
    if (error instanceof ApiError) {
      if (error.kind === "validation") {
        return error.errors.length > 0 ? fieldErrorMessage(error.errors[0]) : t("error.generic");
      }
      return t(`error.${error.kind}`);
    }
    return t("error.generic");
  }

  // =========================================================
  // UTILIDADES DE INTERFAZ
  // =========================================================

  function el(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
  }

  function formatDate(isoString) {
    return new Intl.DateTimeFormat(lang === "en" ? "en-US" : "es-ES", { dateStyle: "medium" }).format(
      new Date(isoString),
    );
  }

  const STATUS_COLORS = {
    open: "bg-amber-100 text-amber-900 ring-amber-300",
    in_progress: "bg-sky-100 text-sky-900 ring-sky-300",
    resolved: "bg-green-100 text-green-900 ring-green-300",
    discarded: "bg-slate-100 text-slate-700 ring-slate-300",
  };

  function statusBadge(status) {
    return el(
      "span",
      `inline-flex whitespace-nowrap rounded-full px-3 py-1 text-xs font-bold ring-1 ${STATUS_COLORS[status] || ""}`,
      t(`status.${status}`),
    );
  }

  // Rellena un <select> con los valores de un campo, conservando la opción seleccionada.
  function fillSelect(select, values, group, placeholderKey) {
    const current = select.value;
    select.replaceChildren();
    if (placeholderKey) select.append(new Option(t(placeholderKey), ""));
    values.forEach((value) => select.append(new Option(t(`${group}.${value}`), value)));
    select.value = values.includes(current) ? current : select.options[0].value;
  }

  window.TrackflowIncidents = {
    STATUSES,
    ORIGINS,
    BRANCHES,
    CATEGORIES,
    SLA_CATEGORIES,
    STATUS_TRANSITIONS,
    STATUS_COLORS,
    TITLE_MAX_LENGTH,
    DESCRIPTION_MAX_LENGTH,
    ApiError,
    api,
    applyI18n,
    el,
    errorMessage,
    fieldErrorMessage,
    fillSelect,
    formatDate,
    statusBadge,
    t,
  };

  document.addEventListener("DOMContentLoaded", () => applyI18n());
})();
