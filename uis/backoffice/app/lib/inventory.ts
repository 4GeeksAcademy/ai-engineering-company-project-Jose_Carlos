// Integración con la API de inventario (/inventory) — CONTEXT-9.
//
// Único punto del backoffice que habla con /inventory: las pantallas llaman a inventoryApi y
// nunca a fetch directamente.
//
// - Todas las peticiones van con `Authorization: Bearer <token>` (backofficeFetch lee el token de
//   localStorage y, si falta, caduca o la API responde 401, se lleva al login).
// - Ningún error se ignora: cualquier 4xx/5xx o fallo de red se convierte en un
//   InventoryApiError con un mensaje en español para mostrar en pantalla y, si procede, el
//   error de cada campo (`fieldErrors`) para pintarlo junto al campo.

import { SessionExpiredError, backofficeFetch } from "./auth";

export const WAREHOUSE_NAMES: Record<string, string> = { LA: "Los Ángeles", ZGZ: "Zaragoza" };

export type Warehouse = "LA" | "ZGZ";

export type Sku = {
  id: number;
  sku: string;
  name: string;
  client_name: string;
  category: string;
  warehouse: Warehouse;
  current_stock: number;
  stock_by_warehouse: Record<string, number>;
};

type SkuRef = Pick<Sku, "id" | "sku" | "name" | "client_name">;

export type InventoryOrder = {
  id: number;
  order_type: "inbound" | "outbound";
  sku_id: number;
  sku: SkuRef;
  quantity: number;
  warehouse: Warehouse;
  reference?: string | null;
  exit_type?: "dispatch" | "loss" | null;
  tracking_number?: string | null;
  user_uuid: string;
  created_at: string;
};

export type StockEntry = { sku_id: number; quantity: number; reference: string; warehouse: string };
export type StockExit = { sku_id: number; quantity: number; exit_type: string; tracking_number: string | null; warehouse: string };

export type FieldErrors = Record<string, string>;
export type InventoryErrorKind = "error" | "network" | "server" | "validation" | "not_found" | "insufficient_stock" | "rejected";

const MESSAGES = {
  network: "No se pudo conectar con el servidor. Comprueba tu conexión e inténtalo de nuevo.",
  unreadable: "El servidor respondió, pero la respuesta no se pudo leer. Inténtalo de nuevo.",
  validation: "Revisa los campos marcados.",
  notFound: "El SKU seleccionado ya no existe. Recarga la página para ver la lista actualizada.",
  server: "Ha ocurrido un problema en el servidor. Inténtalo de nuevo en unos minutos.",
};

export class InventoryApiError extends Error {
  status: number;
  fieldErrors: FieldErrors;
  kind: InventoryErrorKind;
  data: Record<string, unknown>;

  constructor(
    message: string,
    { status = 0, fieldErrors = {}, kind = "error", data = {} }: { status?: number; fieldErrors?: FieldErrors; kind?: InventoryErrorKind; data?: Record<string, unknown> } = {},
  ) {
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

function units(count: string | number) {
  return Number(count) === 1 ? "unidad" : "unidades";
}

function insufficientStockError(detail: string, context: { warehouse?: string }) {
  const [, sku, available, requested] = detail.match(INSUFFICIENT_STOCK) as RegExpMatchArray;
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

type ValidationIssue = { type?: string; msg?: unknown; loc?: unknown; ctx?: { max_length?: number } };

// Errores de validación (422) de FastAPI/Pydantic → texto por campo.
function issueMessage(issue: ValidationIssue): string {
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

function validationError(detail: ValidationIssue[]) {
  const fieldErrors: FieldErrors = {};
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
export function toApiError(status: number, body: { detail?: unknown } | null, context: { warehouse?: string } = {}) {
  const detail = body?.detail;

  if (status === 400 && typeof detail === "string" && INSUFFICIENT_STOCK.test(detail)) {
    return insufficientStockError(detail, context);
  }
  if (status === 422 && Array.isArray(detail)) {
    return validationError(detail as ValidationIssue[]);
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
  const message =
    typeof detail === "string" && detail
      ? `La API ha rechazado la operación: ${detail}`
      : `La API ha rechazado la operación (código ${status}).`;
  return new InventoryApiError(message, { status, kind: "rejected" });
}

// ---------------------------------------------------------------- peticiones

async function request<T>(path: string, { method = "GET", body, context }: { method?: string; body?: unknown; context?: { warehouse?: string } } = {}): Promise<T> {
  const init: RequestInit = { method, headers: {} };
  if (body !== undefined) {
    init.headers = { "Content-Type": "application/json" };
    init.body = JSON.stringify(body);
  }

  let response: Response;
  try {
    response = await backofficeFetch(path, init);
  } catch (error) {
    // Sesión caducada: el guard ya está llevando al login.
    if (error instanceof SessionExpiredError) throw error;
    throw new InventoryApiError(MESSAGES.network, { kind: "network" });
  }

  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    if (response.ok) throw new InventoryApiError(MESSAGES.unreadable, { status: response.status, kind: "server" });
  }
  if (!response.ok) throw toApiError(response.status, payload as { detail?: unknown } | null, context);
  return payload as T;
}

export const inventoryApi = {
  /** GET /inventory/products — todos los SKUs con current_stock y stock_by_warehouse. */
  listSkus: () => request<Sku[]>("/inventory/products"),

  /** GET /inventory/products/{id} — un SKU con su stock actual. */
  getSku: (skuId: number | string) => request<Sku>(`/inventory/products/${encodeURIComponent(skuId)}`),

  /** GET /inventory/orders — entradas y salidas, las más recientes primero. */
  listOrders: () => request<InventoryOrder[]>("/inventory/orders"),

  /** POST /inventory/orders/inbound — recepción de mercancía (StockEntry). */
  registerEntry: (entry: StockEntry) =>
    request<InventoryOrder>("/inventory/orders/inbound", { method: "POST", body: entry, context: { warehouse: entry.warehouse } }),

  /** POST /inventory/orders/outbound — despacho o pérdida (StockExit). */
  registerExit: (stockExit: StockExit) =>
    request<InventoryOrder>("/inventory/orders/outbound", { method: "POST", body: stockExit, context: { warehouse: stockExit.warehouse } }),
};

/** Mensaje de cualquier error que pueda lanzar inventoryApi. */
export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

// ---------------------------------------------------------------- vocabulario y formato

export const CATEGORY_LABELS: Record<string, string> = { fashion: "Moda", electronics: "Electrónica", cosmetics: "Cosmética" };
export const EXIT_TYPE_LABELS: Record<string, string> = { dispatch: "Despacho a cliente", loss: "Pérdida" };

// Umbrales (unidades de un SKU en un almacén):
//   - 0           → "Sin stock"  (rojo):  no se puede despachar nada.
//   - 1 a 49      → "Stock bajo" (ámbar): conviene pedir reposición a la marca cliente.
//   - 50 o más    → "Stock OK"   (verde).
// 50 unidades cubren aproximadamente una semana de despachos de un SKU con salida habitual en
// TrackFlow. Es un umbral único para todos los SKUs: si un cliente necesita otro, se ajusta aquí.
export const LOW_STOCK_THRESHOLD = 50;

const STOCK_LEVELS = {
  out: { label: "Sin stock", icon: "✕", badge: "border-red-200 bg-red-50 text-red-800", text: "text-red-700" },
  low: { label: "Stock bajo", icon: "!", badge: "border-amber-200 bg-amber-50 text-amber-900", text: "text-amber-800" },
  ok: { label: "Stock OK", icon: "✓", badge: "border-emerald-200 bg-emerald-50 text-emerald-800", text: "text-emerald-700" },
};

export type StockLevelKey = keyof typeof STOCK_LEVELS;

export function stockLevel(count: number) {
  if (count <= 0) return { key: "out" as StockLevelKey, ...STOCK_LEVELS.out };
  if (count < LOW_STOCK_THRESHOLD) return { key: "low" as StockLevelKey, ...STOCK_LEVELS.low };
  return { key: "ok" as StockLevelKey, ...STOCK_LEVELS.ok };
}

export function warehouseName(code: string) {
  return WAREHOUSE_NAMES[code] || code;
}

export function formatUnits(count: number | string) {
  const n = Number(count);
  return `${n.toLocaleString("es-ES")} ${n === 1 ? "unidad" : "unidades"}`;
}

export function formatDateTime(iso: string) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString("es-ES", { dateStyle: "medium", timeStyle: "short" });
}

/** Texto de una opción del selector de SKU: por nombre, con su código y almacén. */
export function skuOptionLabel(sku: Sku) {
  return `${sku.name} — ${sku.sku} (${warehouseName(sku.warehouse)})`;
}

/** Entero positivo de un input, o null si no lo es. */
export function positiveInteger(value: string): number | null {
  const text = String(value).trim();
  if (!/^\d+$/.test(text)) return null;
  const n = Number(text);
  return n > 0 && Number.isSafeInteger(n) ? n : null;
}
