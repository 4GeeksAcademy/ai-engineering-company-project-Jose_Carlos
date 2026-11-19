// Propiedades de los eventos del backoffice (TELEMETRY_PLAN.md, secciones 4.3 y 5).
//
// Aquí se construyen las `properties` de cada evento campo a campo, con el vocabulario del plan
// (los_angeles/zaragoza, client_id como slug, rutas como plantilla) y su throttle o deduplicación.
// Todo acaba en `track()`: este archivo no envía nada por su cuenta.
//
// Nunca entra aquí un dato personal: ni emails, ni nombres, ni valores tecleados, ni mensajes
// de error, ni ids de la URL (las rutas se reducen a plantilla).

import { hasUnsavedForm } from "./form-abandonment";
import { tokenClaims, track } from "./telemetry";

// ---------------------------------------------------------------- vocabulario (sección 4.3)

const WAREHOUSES: Record<string, string> = { LA: "los_angeles", ZGZ: "zaragoza" };
const COUNTRIES: Record<string, string> = { los_angeles: "US", zaragoza: "ES" };

/** Slug determinista de la marca cliente: `GlowLab Cosmetics` → `glowlab_cosmetics` (igual que la API). */
export function clientId(clientName: string): string {
  return clientName
    .normalize("NFKD")
    .replace(/[^\x00-\x7f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
}

type SkuFacts = { sku: string; client_name: string; category?: string };

/** Los campos mínimos del BRIEFING para un movimiento de un SKU. */
export function inventoryProperties(sku: SkuFacts, warehouseCode: string, quantity: number) {
  const warehouse = WAREHOUSES[warehouseCode] ?? null;
  return {
    warehouse,
    country: warehouse ? COUNTRIES[warehouse] : null,
    client_id: clientId(sku.client_name),
    product_id: sku.sku,
    product_category: sku.category ?? null,
    quantity,
  };
}

// Pantallas con un segmento dinámico: el id real nunca sale del navegador.
const DYNAMIC_PAGES: Array<[RegExp, string]> = [[/^\/talent\/records\/[^/]+$/, "/talent/records/[id]"]];

/** Ruta de una pantalla como plantilla de Next.js, sin ids, query string ni barra final. */
export function pageRoute(pathname: string): string {
  const path = (pathname.split(/[?#]/)[0] || "/").replace(/\/+$/, "") || "/";
  for (const [pattern, template] of DYNAMIC_PAGES) if (pattern.test(path)) return template;
  // Cualquier otro segmento que no sea una palabra en minúsculas (ids, códigos) se oculta.
  return path.replace(/\/(?![a-z][a-z0-9-]*(?:\/|$))[^/]+/g, "/[id]");
}

const SECTIONS: Record<string, string> = {
  "": "home",
  incidents: "incidents",
  suppliers: "suppliers",
  inventory: "inventory",
  talent: "talent",
  account: "account",
  login: "auth",
  register: "auth",
  "forgot-password": "auth",
  "reset-password": "auth",
};

/** Sección de la navegación (`backoffice-header.tsx`) a la que pertenece una pantalla, o null. */
export function pageSection(route: string): string | null {
  return SECTIONS[route.split("/")[1] ?? ""] ?? null;
}

/** Ruta de la API como plantilla (`/inventory/products/{id}`), sin query string. */
export function apiRoute(url: string): string {
  let path = url;
  try {
    path = new URL(url, "http://localhost").pathname;
  } catch {
    // Ya era una ruta.
  }
  path = path.replace(/\/+$/, "") || "/";
  return path.replace(/\/(?![a-z][a-z0-9-]*(?:\/|$))[^/]+/g, "/{id}");
}

// ---------------------------------------------------------------- inventario

type CreatedOrder = {
  id: number;
  sku: SkuFacts;
  quantity: number;
  warehouse: string;
  exit_type?: string | null;
  stock_after?: number;
};

/** 201 de una entrada o salida: `inbound_order_created`, `outbound_order_created` o `stock_loss_recorded`. */
export function trackOrderCreated(kind: "inbound" | "outbound", order: CreatedOrder, requestId: string): void {
  if (typeof order.stock_after !== "number") return;
  const base = inventoryProperties(order.sku, order.warehouse, order.quantity);
  if (kind === "inbound") {
    track("inbound_order_created", { ...base, inbound_order_id: order.id, stock_after: order.stock_after }, { requestId });
  } else {
    const eventType = order.exit_type === "loss" ? "stock_loss_recorded" : "outbound_order_created";
    track(eventType, { ...base, outbound_order_id: order.id, stock_after: order.stock_after }, { requestId });
  }
}

/** 400 de stock insuficiente: `outbound_order_rejected` (el SKU viene del formulario). */
export function trackOutboundRejected(
  sku: SkuFacts,
  stockExit: { quantity: number; warehouse: string; exit_type: string },
  available: number,
  requestId: string,
): void {
  track(
    "outbound_order_rejected",
    {
      ...inventoryProperties(sku, stockExit.warehouse, stockExit.quantity),
      available_quantity: Math.max(available, 0),
      exit_type: stockExit.exit_type,
    },
    { requestId },
  );
}

// ---------------------------------------------------------------- autenticación

export type LoginFailureReason = "invalid_credentials" | "validation_error" | "network_error" | "server_error";

/** Un intento de login fallido. Solo el motivo: nunca el email ni la contraseña. */
export function trackLoginFailed(reason: LoginFailureReason): void {
  track("login_failed", { failure_reason: reason });
}

// Un evento por token: tras detectarlo se borra el token, y el resto de llamadas en vuelo no repiten.
let lastExpiredToken: string | null = null;

/** La sesión ha caducado. Se llama ANTES de borrar el token (de él salen userId y la edad). */
export function trackSessionExpired(detection: "client_token_check" | "api_401", token: string | null): void {
  if (!token || token === lastExpiredToken) return;
  lastExpiredToken = token;
  const issuedAt = tokenClaims(token)?.iat;
  track("session_expired", {
    detection,
    page_route: pageRoute(window.location.pathname),
    session_age_ms: typeof issuedAt === "number" ? Math.max(0, Date.now() - issuedAt * 1000) : 0,
    had_unsaved_form: hasUnsavedForm(),
  });
}

// ---------------------------------------------------------------- errores

const API_FAILURE_THROTTLE_MS = 30_000;
const lastApiFailure = new Map<string, number>();

/** Fallo de red, tiempo agotado o 5xx de una llamada. Uno por (ruta, tipo) cada 30 s. */
export function trackApiRequestFailed(
  url: string,
  method: string,
  failure: { kind: "network" | "timeout" | "server_error"; status?: number },
): void {
  const route = apiRoute(url);
  const key = `${route}|${failure.kind}`;
  const now = Date.now();
  if (now - (lastApiFailure.get(key) ?? -Infinity) < API_FAILURE_THROTTLE_MS) return;
  lastApiFailure.set(key, now);
  track("api_request_failed", {
    api_route: route,
    http_method: method.toUpperCase(),
    failure_kind: failure.kind,
    status_code: failure.kind === "server_error" ? failure.status ?? null : null,
  });
}

/** `fetch` lanzó: ¿fue el tiempo de espera (AbortSignal.timeout) o la red? */
export function failureKind(error: unknown): "network" | "timeout" {
  return error instanceof DOMException && error.name === "TimeoutError" ? "timeout" : "network";
}

/**
 * FNV-1a de 64 bits en hexadecimal (16 caracteres). Agrupa errores; no es criptográfico. Recorre
 * las unidades UTF-16 del texto (en ASCII, lo mismo que sus bytes): no necesita TextEncoder.
 */
// Constantes de FNV-1a: BigInt("…") y no literales `…n`, que el `target` de tsconfig no admite.
const FNV_OFFSET = BigInt("0xcbf29ce484222325");
const FNV_PRIME = BigInt("0x100000001b3");
const UINT64 = BigInt("0xffffffffffffffff");

export function fnv1a64(text: string): string {
  let hash = FNV_OFFSET;
  for (let i = 0; i < text.length; i++) {
    hash ^= BigInt(text.charCodeAt(i));
    hash = (hash * FNV_PRIME) & UINT64;
  }
  return hash.toString(16).padStart(16, "0");
}

const ERROR_DEDUP_MS = 60_000;
const MAX_ERRORS_PER_SESSION = 20;
const errorWindows = new Map<string, { startedAt: number; repeats: number }>();
let errorsSent = 0;

/** Primera línea de la pila que no es el propio mensaje, sin query string ni hash. */
function firstFrame(stack: string | undefined): string {
  const frame = (stack ?? "").split("\n").map((line) => line.trim()).find((line) => /:\d+(:\d+)?\)?$/.test(line)) ?? "";
  return frame.replace(/[?#][^:)]*/g, "");
}

/**
 * Error no controlado. Solo el tipo y un fingerprint: el mensaje puede contener datos de la
 * pantalla. Uno por fingerprint cada 60 s (las repeticiones van en `occurrences`), 20 por sesión.
 */
export function trackFrontendError(error: unknown, source: "window_error" | "unhandled_rejection" | "error_boundary"): void {
  const rawName = error instanceof Error ? error.name : typeof error;
  const name = /^[A-Za-z_][A-Za-z0-9_]*$/.test(rawName) ? rawName.slice(0, 80) : "UnknownError";
  const fingerprint = fnv1a64(`${name}|${firstFrame(error instanceof Error ? error.stack : undefined)}`);
  const now = Date.now();
  const window_ = errorWindows.get(fingerprint);
  if (window_ && now - window_.startedAt < ERROR_DEDUP_MS) {
    window_.repeats += 1;
    return;
  }
  if (errorsSent >= MAX_ERRORS_PER_SESSION) return;
  errorsSent += 1;
  // Las repeticiones de la ventana anterior se suman a este evento.
  errorWindows.set(fingerprint, { startedAt: now, repeats: 0 });
  track("frontend_error_captured", {
    page_route: pageRoute(window.location.pathname),
    error_source: source,
    error_name: name,
    error_fingerprint: fingerprint,
    occurrences: 1 + (window_?.repeats ?? 0),
  });
}
