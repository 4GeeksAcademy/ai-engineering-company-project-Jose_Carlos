// Directorio de proveedores (/suppliers): vocabulario de CONTEXT-7 y llamadas a la API.

import { SessionExpiredError, backofficeFetch } from "./auth";

// Valores exactos de audit/CONTEXTS/CONTEXT-7-trackflow.es.md
export const VALID_CATEGORIES = [
  "carrier_last_mile",
  "carrier_international",
  "warehouse_supplies",
  "packaging_materials",
  "reverse_logistics",
  "fleet_maintenance",
  "it_and_wms_software",
  "cleaning_and_facilities",
] as const;

export const CATEGORY_LABELS: Record<string, string> = {
  carrier_last_mile: "Carrier última milla",
  carrier_international: "Carrier internacional",
  warehouse_supplies: "Suministros de almacén",
  packaging_materials: "Material de embalaje",
  reverse_logistics: "Logística inversa",
  fleet_maintenance: "Mantenimiento de flota",
  it_and_wms_software: "Software IT / WMS",
  cleaning_and_facilities: "Limpieza e instalaciones",
};

export const CURRENCY_BY_COUNTRY: Record<string, string> = { USA: "USD", Spain: "EUR" };

export const STATUS_LABELS: Record<string, string> = { active: "Activo", suspended: "Suspendido" };

export type SupplierStatus = "active" | "suspended";

export type Supplier = {
  id: number;
  name: string;
  country: string;
  categories: string[];
  rate_per_shipment: number;
  currency: string;
  status: SupplierStatus;
  service_zone: string | null;
  contact_email: string | null;
  notes: string | null;
  updated_at: string;
};

export type SupplierDraft = Omit<Supplier, "id" | "updated_at">;

const FIELD_LABELS: Record<string, string> = {
  name: "Nombre",
  country: "País",
  categories: "Categorías",
  rate_per_shipment: "Tarifa por envío",
  currency: "Moneda",
  status: "Estado",
  service_zone: "Zona de servicio",
  contact_email: "Email de contacto",
  notes: "Notas",
};

// Motivo del error según el `type` de la validación de FastAPI.
const ISSUE_MESSAGES: Record<string, string> = {
  missing: "es obligatorio",
  string_too_short: "es obligatorio",
  too_short: "necesita al menos un valor",
  greater_than: "debe ser mayor que 0",
};

// Convierte el error de la API en un texto propio para el usuario: nunca se muestra el
// mensaje del servidor (inglés técnico) ni el código de estado.
// 422 → detail es una lista [{type, loc}]; el resto se decide por el código.
function formatApiError(body: { detail?: unknown } | null, status: number): string {
  const detail = body?.detail;

  if (status === 422 && Array.isArray(detail)) {
    const messages = (detail as Array<{ type?: string; loc?: unknown[] }>).map((issue) => {
      const field = (issue.loc || []).filter((part) => part !== "body")[0];
      const label = FIELD_LABELS[String(field)];
      // Sin campo: es la regla que relaciona país y moneda.
      if (!label) return "La moneda no corresponde al país del contrato.";
      return `${label}: ${ISSUE_MESSAGES[issue.type ?? ""] || "el valor no es válido"}.`;
    });
    return [...new Set(messages)].join(" ");
  }

  if (status === 404) return "Este proveedor ya no existe. Actualiza el listado.";
  if (status >= 500) return "Ha ocurrido un problema en el servidor. Inténtalo de nuevo en unos minutos.";
  return "No se pudo completar la operación. Revisa los datos e inténtalo de nuevo.";
}

async function apiRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await backofficeFetch(path, {
      ...init,
      headers: init.body ? { "Content-Type": "application/json" } : undefined,
    });
  } catch (error) {
    // Sesión caducada: el guard ya está llevando al login.
    if (error instanceof SessionExpiredError) throw error;
    throw new Error("No se pudo conectar con el servidor. Comprueba tu conexión e inténtalo de nuevo.");
  }

  const body = (await response.json().catch(() => null)) as { detail?: unknown } | null;
  if (!response.ok) throw new Error(formatApiError(body, response.status));
  // Respuesta correcta pero ilegible: se trata como un fallo del servidor.
  if (body === null) throw new Error(formatApiError(null, 500));
  return body as T;
}

export const suppliersApi = {
  list(country: string, category: string) {
    const params = new URLSearchParams();
    if (country) params.set("country", country);
    if (category) params.set("category", category);
    const query = params.toString();
    return apiRequest<Supplier[]>(query ? `/suppliers?${query}` : "/suppliers");
  },
  create: (data: SupplierDraft) => apiRequest<Supplier>("/suppliers", { method: "POST", body: JSON.stringify(data) }),
  updateRate: (id: number, rate: number) =>
    apiRequest<Supplier>(`/suppliers/${id}/rate`, { method: "PATCH", body: JSON.stringify({ rate_per_shipment: rate }) }),
  updateStatus: (id: number, status: SupplierStatus) =>
    apiRequest<Supplier>(`/suppliers/${id}/status`, { method: "PATCH", body: JSON.stringify({ status }) }),
};

export function formatMoney(amount: number, currency: string): string {
  return new Intl.NumberFormat("es-ES", { style: "currency", currency }).format(amount);
}

export function formatDateTime(isoString: string): string {
  return new Intl.DateTimeFormat("es-ES", { dateStyle: "short", timeStyle: "short" }).format(new Date(isoString));
}
