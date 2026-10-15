// Integración con la API de inventario (/inventory) — CONTEXT-9.
//
// Único punto del backoffice que habla con /inventory: las páginas llaman a
// window.TrackflowInventoryApi y nunca a fetch directamente.
//
// - Todas las peticiones van con `Authorization: Bearer <token>` (TrackflowAuth.authFetch lee el
//   token de localStorage y, si falta, caduca o la API responde 401, lleva al login).
// - Ningún error se ignora: cualquier 4xx/5xx o fallo de red se convierte en un
//   InventoryApiError con un mensaje en español para mostrar en pantalla y, si procede, el
//   error de cada campo (`fieldErrors`) para pintarlo junto al campo.
(function () {
  const auth = window.TrackflowAuth;

  const WAREHOUSE_NAMES = { LA: "Los Ángeles", ZGZ: "Zaragoza" };

  const MESSAGES = {
    network: "No se pudo conectar con el servidor. Comprueba tu conexión e inténtalo de nuevo.",
    unreadable: "El servidor respondió, pero la respuesta no se pudo leer. Inténtalo de nuevo.",
    validation: "Revisa los campos marcados.",
    notFound: "El SKU seleccionado ya no existe. Recarga la página para ver la lista actualizada.",
    server: "Ha ocurrido un problema en el servidor. Inténtalo de nuevo en unos minutos.",
  };

  class InventoryApiError extends Error {
    constructor(message, { status = 0, fieldErrors = {}, kind = "error", data = {} } = {}) {
      super(message);
      this.name = "InventoryApiError";
      this.status = status;
      this.fieldErrors = fieldErrors;
      this.kind = kind;
      this.data = data;
    }
  }

  // ---------------------------------------------------------------- traducción de errores

  // 400 de una salida sin stock suficiente (texto exacto de CONTEXT-9, regla 2).
  const INSUFFICIENT_STOCK = /^Insufficient stock for SKU '(.+)'\. Available: (-?\d+), requested: (\d+)\.$/;

  function insufficientStockError(detail, context) {
    const [, sku, available, requested] = detail.match(INSUFFICIENT_STOCK);
    const where = context.warehouse ? ` en ${WAREHOUSE_NAMES[context.warehouse] || context.warehouse}` : "";
    const message =
      `Stock insuficiente para ${sku}${where}: hay ${available} ${units(available)} disponibles ` +
      `y has pedido ${requested}. No se ha registrado la salida.`;
    return new InventoryApiError(message, {
      status: 400,
      kind: "insufficient_stock",
      fieldErrors: { quantity: message },
      data: { sku, available: Number(available), requested: Number(requested) },
    });
  }

  function units(count) {
    return Number(count) === 1 ? "unidad" : "unidades";
  }

  // Errores de validación (422) de FastAPI/Pydantic → texto por campo.
  function issueMessage(issue) {
    const msg = String(issue.msg || "");
    switch (issue.type) {
      case "missing":
      case "string_too_short":
        return "Este campo es obligatorio.";
      case "greater_than":
        return "Debe ser mayor que 0.";
      case "less_than_equal":
        return "La cantidad es demasiado grande.";
      case "int_type":
      case "int_parsing":
      case "int_from_float":
        return "Introduce un número entero de unidades.";
      case "string_too_long":
        return issue.ctx?.max_length ? `Como máximo ${issue.ctx.max_length} caracteres.` : "El texto es demasiado largo.";
      case "literal_error":
        return "Elige una de las opciones de la lista.";
      case "extra_forbidden":
        return "Este dato no se puede enviar.";
      default:
        if (msg.includes("tracking_number is required")) return "El número de seguimiento es obligatorio en un despacho.";
        if (msg.includes("tracking_number must be null")) return "Una pérdida no lleva número de seguimiento.";
        return "El valor no es válido.";
    }
  }

  function validationError(detail) {
    const fieldErrors = {};
    for (const issue of detail) {
      const loc = Array.isArray(issue.loc) ? issue.loc : [];
      let field = loc.length > 1 ? String(loc[loc.length - 1]) : "body";
      // La regla del número de seguimiento se valida sobre el cuerpo entero (loc = ["body"]).
      if (field === "body" && String(issue.msg || "").includes("tracking_number")) field = "tracking_number";
      fieldErrors[field] ??= issueMessage(issue);
    }
    return new InventoryApiError(MESSAGES.validation, { status: 422, kind: "validation", fieldErrors });
  }

  /** Convierte una respuesta de error de la API en un InventoryApiError con mensaje legible. */
  function toApiError(status, body, context = {}) {
    const detail = body && body.detail;

    if (status === 400 && typeof detail === "string" && INSUFFICIENT_STOCK.test(detail)) {
      return insufficientStockError(detail, context);
    }
    if (status === 422 && Array.isArray(detail)) {
      return validationError(detail);
    }
    if (status === 404) {
      return new InventoryApiError(MESSAGES.notFound, { status, kind: "not_found", fieldErrors: { sku_id: MESSAGES.notFound } });
    }
    if (status >= 500) {
      // El 503 (Supabase no responde) y el 500 de la API ya traen un texto en español.
      const message = typeof detail === "string" && detail ? detail : MESSAGES.server;
      return new InventoryApiError(message, { status, kind: "server" });
    }
    // Cualquier otro 4xx: se muestra el mensaje de la API, nunca se descarta.
    const message = typeof detail === "string" && detail
      ? `La API ha rechazado la operación: ${detail}`
      : `La API ha rechazado la operación (código ${status}).`;
    return new InventoryApiError(message, { status, kind: "rejected" });
  }

  // ---------------------------------------------------------------- peticiones

  async function request(path, { method = "GET", body, context } = {}) {
    const options = { method, headers: {} };
    if (body !== undefined) {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(body);
    }

    let response;
    try {
      response = await auth.authFetch(auth.apiUrl(path), options);
    } catch (error) {
      // Sesión caducada: authFetch ya está llevando al login.
      if (error instanceof auth.SessionExpiredError) throw error;
      throw new InventoryApiError(MESSAGES.network, { kind: "network" });
    }

    let payload = null;
    try {
      payload = await response.json();
    } catch {
      if (response.ok) throw new InventoryApiError(MESSAGES.unreadable, { status: response.status, kind: "server" });
    }
    if (!response.ok) throw toApiError(response.status, payload, context);
    return payload;
  }

  window.TrackflowInventoryApi = {
    InventoryApiError,
    WAREHOUSE_NAMES,
    toApiError,

    /** GET /inventory/products — todos los SKUs con current_stock y stock_by_warehouse. */
    listSkus: () => request("/inventory/products"),

    /** GET /inventory/products/{id} — un SKU con su stock actual. */
    getSku: (skuId) => request(`/inventory/products/${encodeURIComponent(skuId)}`),

    /** GET /inventory/orders — entradas y salidas, las más recientes primero. */
    listOrders: () => request("/inventory/orders"),

    /** POST /inventory/orders/inbound — recepción de mercancía (StockEntry). */
    registerEntry: (entry) =>
      request("/inventory/orders/inbound", { method: "POST", body: entry, context: { warehouse: entry.warehouse } }),

    /** POST /inventory/orders/outbound — despacho o pérdida (StockExit). */
    registerExit: (stockExit) =>
      request("/inventory/orders/outbound", { method: "POST", body: stockExit, context: { warehouse: stockExit.warehouse } }),

    /** GET /auth/me — usuario de la sesión (para marcar sus propios movimientos). */
    getCurrentUser: () => request("/auth/me"),
  };
})();
