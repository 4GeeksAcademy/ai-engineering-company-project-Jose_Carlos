import { login } from "../app/lib/auth";
import { InventoryApiError, inventoryApi } from "../app/lib/inventory";
import {
  BATCH_SIZE,
  FLUSH_INTERVAL_MS,
  TelemetryEnvelope,
  TelemetryService,
  startTelemetrySession,
  telemetryService,
  telemetrySessionId,
  track,
} from "../app/lib/telemetry";
import {
  apiRoute,
  clientId,
  fnv1a64,
  pageRoute,
  pageSection,
  trackApiRequestFailed,
  trackFrontendError,
  trackSessionExpired,
} from "../app/lib/telemetry-events";
import { TELEMETRY_SCHEMA_VERSIONS } from "../app/lib/telemetry-schema";

// =========================================================
// UTILIDADES DE PRUEBA
// =========================================================

const ENDPOINT = "http://telemetry.test/events";
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const USER_ID = "5d0f7a52-8a0c-4b8e-9f3e-2c1d4b6a8e10";

function jwt(claims: Record<string, unknown>) {
  const encode = (value: object) => btoa(JSON.stringify(value)).replace(/=+$/, "");
  return `${encode({ alg: "HS256" })}.${encode(claims)}.signature`;
}

// jsdom no trae Response: basta con lo que leen el servicio y las capas de API.
function apiResponse(status: number, body?: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

// jsdom no implementa Blob.text().
function readBlob(blob: Blob): Promise<string> {
  return new Promise((resolve) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as string);
    reader.readAsText(blob);
  });
}

const PAGE_VIEW = { page_route: "/inventory/products", section: "inventory", previous_route: null };

function sentBatches(fetchMock: jest.Mock): TelemetryEnvelope[][] {
  return fetchMock.mock.calls
    .filter(([url]) => url === ENDPOINT)
    .map(([, init]) => JSON.parse((init as RequestInit).body as string).events);
}

let fetchMock: jest.Mock;
let beaconMock: jest.Mock;

beforeEach(() => {
  jest.useFakeTimers();
  fetchMock = jest.fn().mockResolvedValue(apiResponse(200, { received: 1 }));
  global.fetch = fetchMock;
  beaconMock = jest.fn().mockReturnValue(true);
  Object.defineProperty(navigator, "sendBeacon", { value: beaconMock, configurable: true });
  window.localStorage.clear();
  window.sessionStorage.clear();
});

afterEach(() => {
  jest.useRealTimers();
  jest.restoreAllMocks();
});

// =========================================================
// TELEMETRYSERVICE: ENVELOPE
// =========================================================

describe("TelemetryService: envelope", () => {
  it("completa todos los campos del envelope; quien llama solo pasa tipo y propiedades", () => {
    window.localStorage.setItem("trackflow.access_token", jwt({ sub: USER_ID, iat: 1 }));
    const service = new TelemetryService(() => ENDPOINT);

    service.track("page_viewed", PAGE_VIEW);
    service.flush();

    const [[event]] = sentBatches(fetchMock);
    expect(Object.keys(event).sort()).toEqual(
      ["environment", "eventId", "event_type", "properties", "requestId", "schemaVersion", "sessionId", "source", "timestamp", "userId"],
    );
    expect(event.eventId).toMatch(UUID);
    expect(event.timestamp).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/);
    expect(event.sessionId).toMatch(UUID);
    expect(event.userId).toBe(USER_ID);
    expect(event.schemaVersion).toBe(TELEMETRY_SCHEMA_VERSIONS.page_viewed);
    expect(event.requestId).toMatch(UUID);
    expect(event.source).toBe("backoffice_web");
    expect(event.environment).toBe("test");
    expect(event.properties).toEqual(PAGE_VIEW);
  });

  it("el timestamp es el de la captura, no el del envío", () => {
    const service = new TelemetryService(() => ENDPOINT);
    jest.setSystemTime(new Date("2026-10-27T09:00:00.000Z"));
    service.track("page_viewed", PAGE_VIEW);
    jest.setSystemTime(new Date("2026-10-27T09:00:09.000Z"));
    service.flush();

    expect(sentBatches(fetchMock)[0][0].timestamp).toBe("2026-10-27T09:00:00.000Z");
  });

  it("sin sesión iniciada el userId es null", () => {
    const service = new TelemetryService(() => ENDPOINT);
    service.track("login_failed", { failure_reason: "invalid_credentials" });
    service.flush();

    expect(sentBatches(fetchMock)[0][0].userId).toBeNull();
  });

  it("usa el requestId de la llamada HTTP si se lo pasan, y uno nuevo si no", () => {
    const service = new TelemetryService(() => ENDPOINT);
    const requestId = "c4e6a8b0-1d3f-4a5b-8c7d-9e0f1a2b3c4d";
    service.track("page_viewed", PAGE_VIEW, { requestId });
    service.track("page_viewed", PAGE_VIEW, { requestId: "no-es-un-uuid" });
    service.flush();

    const [first, second] = sentBatches(fetchMock)[0];
    expect(first.requestId).toBe(requestId);
    expect(second.requestId).toMatch(UUID);
    expect(second.requestId).not.toBe(requestId);
  });

  it("la sesión de telemetría se mantiene en la pestaña y cambia al rotarla (login/logout)", () => {
    const first = telemetrySessionId();
    expect(telemetrySessionId()).toBe(first);

    startTelemetrySession();

    expect(telemetrySessionId()).toMatch(UUID);
    expect(telemetrySessionId()).not.toBe(first);
  });

  it("sin NEXT_PUBLIC_TELEMETRY_ENDPOINT no envía nada y avisa una sola vez", () => {
    const warn = jest.spyOn(console, "warn").mockImplementation(() => {});
    const service = new TelemetryService(() => null);

    service.track("page_viewed", PAGE_VIEW);
    service.track("page_viewed", PAGE_VIEW);
    service.flush();
    jest.advanceTimersByTime(FLUSH_INTERVAL_MS);

    expect(fetchMock).not.toHaveBeenCalled();
    expect(warn).toHaveBeenCalledTimes(1);
  });
});

// =========================================================
// TELEMETRYSERVICE: LOTES, REINTENTOS Y SENDBEACON
// =========================================================

describe("TelemetryService: entrega", () => {
  it("agrupa los eventos y los envía a los 10 s, en un solo POST {events: [...]}", () => {
    const service = new TelemetryService(() => ENDPOINT);
    service.track("page_viewed", PAGE_VIEW);
    service.track("page_viewed", PAGE_VIEW);

    jest.advanceTimersByTime(FLUSH_INTERVAL_MS - 1);
    expect(fetchMock).not.toHaveBeenCalled();
    jest.advanceTimersByTime(1);

    expect(sentBatches(fetchMock)).toHaveLength(1);
    expect(sentBatches(fetchMock)[0]).toHaveLength(2);
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ method: "POST", keepalive: true });
  });

  it("al llegar a 20 eventos envía sin esperar al temporizador", () => {
    const service = new TelemetryService(() => ENDPOINT);
    for (let i = 0; i < BATCH_SIZE; i++) service.track("page_viewed", PAGE_VIEW);

    expect(sentBatches(fetchMock)).toHaveLength(1);
    expect(sentBatches(fetchMock)[0]).toHaveLength(BATCH_SIZE);
  });

  it("reintenta un 5xx hasta 3 veces con espera exponencial y después descarta el lote", async () => {
    fetchMock.mockResolvedValue(apiResponse(503));
    const service = new TelemetryService(() => ENDPOINT);
    service.track("page_viewed", PAGE_VIEW);
    service.flush();

    for (const wait of [1000, 2000, 4000]) {
      await jest.advanceTimersByTimeAsync(wait - 1);
      const before = fetchMock.mock.calls.length;
      await jest.advanceTimersByTimeAsync(1);
      expect(fetchMock.mock.calls.length).toBe(before + 1);
    }
    await jest.advanceTimersByTimeAsync(60_000);

    expect(fetchMock).toHaveBeenCalledTimes(4);
  });

  it("reintenta también un fallo de red", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    const service = new TelemetryService(() => ENDPOINT);
    service.track("page_viewed", PAGE_VIEW);
    service.flush();

    await jest.advanceTimersByTimeAsync(1000);

    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("no reintenta un 4xx: el lote está mal y repetirlo no lo arregla", async () => {
    fetchMock.mockResolvedValue(apiResponse(422));
    const service = new TelemetryService(() => ENDPOINT);
    service.track("page_viewed", PAGE_VIEW);
    service.flush();

    await jest.advanceTimersByTimeAsync(60_000);

    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("al ocultar la pestaña vacía la cola con sendBeacon y un cuerpo text/plain", async () => {
    const service = new TelemetryService(() => ENDPOINT);
    service.track("page_viewed", PAGE_VIEW);

    Object.defineProperty(document, "visibilityState", { value: "hidden", configurable: true });
    document.dispatchEvent(new Event("visibilitychange", { bubbles: true }));
    Object.defineProperty(document, "visibilityState", { value: "visible", configurable: true });

    expect(beaconMock).toHaveBeenCalledTimes(1);
    const [url, blob] = beaconMock.mock.calls[0] as [string, Blob];
    expect(url).toBe(ENDPOINT);
    expect(blob.type).toBe("text/plain;charset=utf-8");
    expect(JSON.parse(await readBlob(blob)).events).toHaveLength(1);
    // La cola quedó vacía: el temporizador ya no envía nada.
    jest.advanceTimersByTime(FLUSH_INTERVAL_MS);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("los lotes que esperaban reintento también salen por sendBeacon al cerrar", async () => {
    fetchMock.mockResolvedValue(apiResponse(503));
    const service = new TelemetryService(() => ENDPOINT);
    service.track("page_viewed", PAGE_VIEW);
    service.flush();
    await jest.advanceTimersByTimeAsync(0);

    service.flushOnHide("pagehide");

    expect(beaconMock).toHaveBeenCalledTimes(1);
    await jest.advanceTimersByTimeAsync(60_000);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("los hooks de onHide corren antes del envío y saben si la pestaña se cierra", async () => {
    const service = new TelemetryService(() => ENDPOINT);
    const reasons: string[] = [];
    service.onHide((reason) => {
      reasons.push(reason);
      service.track("page_viewed", PAGE_VIEW);
    });

    service.flushOnHide("hidden");
    service.flushOnHide("pagehide");

    expect(reasons).toEqual(["hidden", "pagehide"]);
    expect(beaconMock).toHaveBeenCalledTimes(2);
  });

  it("si sendBeacon no acepta el lote, lo intenta con fetch keepalive", () => {
    beaconMock.mockReturnValue(false);
    const service = new TelemetryService(() => ENDPOINT);
    service.track("page_viewed", PAGE_VIEW);

    service.flushOnHide("pagehide");

    expect(sentBatches(fetchMock)).toHaveLength(1);
  });

  it("track nunca lanza, aunque falle el servicio", () => {
    jest.spyOn(telemetryService, "track").mockImplementation(() => {
      throw new Error("boom");
    });

    expect(() => track("page_viewed", PAGE_VIEW)).not.toThrow();
  });
});

// =========================================================
// VOCABULARIO DEL PLAN
// =========================================================

describe("vocabulario del plan", () => {
  it.each([
    ["PureStep Footwear", "purestep_footwear"],
    ["GlowLab Cosmetics", "glowlab_cosmetics"],
    ["Café & Moda, S.L.", "cafe_moda_s_l"],
  ])("client_id de %s es %s (el mismo slug que la API)", (name, slug) => {
    expect(clientId(name)).toBe(slug);
  });

  it.each([
    ["/", "/"],
    ["/inventory/products/", "/inventory/products"],
    ["/talent/records/rec-123", "/talent/records/[id]"],
    ["/incidents?search=ana", "/incidents"],
    ["/foo/42", "/foo/[id]"],
  ])("la ruta %s se reduce a la plantilla %s", (path, template) => {
    expect(pageRoute(path)).toBe(template);
  });

  it("cada pantalla pertenece a una sección de la navegación", () => {
    expect(pageSection("/")).toBe("home");
    expect(pageSection("/inventory/orders/inbound")).toBe("inventory");
    expect(pageSection("/login")).toBe("auth");
    expect(pageSection("/account/profile")).toBe("account");
    expect(pageSection("/no-existe")).toBeNull();
  });

  it("las rutas de la API pierden ids y query string", () => {
    expect(apiRoute("http://localhost:8000/inventory/products/12?x=1")).toBe("/inventory/products/{id}");
    expect(apiRoute("/inventory/orders/outbound")).toBe("/inventory/orders/outbound");
  });

  it("el fingerprint es FNV-1a de 64 bits", () => {
    expect(fnv1a64("")).toBe("cbf29ce484222325");
    expect(fnv1a64("a")).toBe("af63dc4c8601ec8c");
  });
});

// =========================================================
// EVENTOS
// =========================================================

describe("eventos del backoffice", () => {
  let tracked: Array<{ type: string; properties: Record<string, unknown>; requestId?: string | null }>;

  beforeEach(() => {
    tracked = [];
    jest.spyOn(telemetryService, "track").mockImplementation((type, properties, options) => {
      tracked.push({ type, properties, requestId: options?.requestId });
    });
  });

  const json = (body: unknown, status = 200) => apiResponse(status, body);

  it("login_failed lleva solo el motivo, nunca el email ni la contraseña", async () => {
    fetchMock.mockResolvedValueOnce(json({ detail: "Incorrect" }, 401));
    await expect(login("ana@trackflow.com", "s3cret")).rejects.toThrow();
    fetchMock.mockResolvedValueOnce(json({ detail: [] }, 422));
    await expect(login("ana", "x")).rejects.toThrow();
    fetchMock.mockResolvedValueOnce(json({ detail: "boom" }, 500));
    await expect(login("ana@trackflow.com", "s3cret")).rejects.toThrow();
    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    await expect(login("ana@trackflow.com", "s3cret")).rejects.toThrow();

    const failures = tracked.filter((event) => event.type === "login_failed");
    expect(failures.map((event) => event.properties)).toEqual([
      { failure_reason: "invalid_credentials" },
      { failure_reason: "validation_error" },
      { failure_reason: "server_error" },
      { failure_reason: "network_error" },
    ]);
    expect(JSON.stringify(tracked)).not.toMatch(/ana|s3cret/);
  });

  it("las llamadas a la API llevan X-Request-Id y X-Session-Id", async () => {
    fetchMock.mockResolvedValueOnce(json({ detail: "Incorrect" }, 401));
    await expect(login("ana@trackflow.com", "s3cret")).rejects.toThrow();

    const headers = new Headers((fetchMock.mock.calls[0][1] as RequestInit).headers);
    expect(headers.get("X-Request-Id")).toMatch(UUID);
    expect(headers.get("X-Session-Id")).toBe(telemetrySessionId());
  });

  it("una entrada registrada emite inbound_order_created con el X-Request-Id de su llamada", async () => {
    window.localStorage.setItem("trackflow.access_token", jwt({ sub: USER_ID, iat: 1, exp: 4102444800 }));
    fetchMock.mockResolvedValueOnce(
      json({
        id: 7, order_type: "inbound", sku_id: 1, quantity: 100, warehouse: "LA", reference: "PO-1", user_uuid: USER_ID,
        created_at: "2026-10-27T09:00:00Z", stock_after: 148,
        sku: { id: 1, sku: "CLT-SNK-W-42", name: "Zapatilla", client_name: "PureStep Footwear", category: "fashion" },
      }, 201),
    );

    await inventoryApi.registerEntry({ sku_id: 1, quantity: 100, reference: "PO-1", warehouse: "LA" });

    const sentRequestId = new Headers((fetchMock.mock.calls[0][1] as RequestInit).headers).get("X-Request-Id");
    expect(tracked).toEqual([{
      type: "inbound_order_created",
      requestId: sentRequestId,
      properties: {
        warehouse: "los_angeles", country: "US", client_id: "purestep_footwear", product_id: "CLT-SNK-W-42",
        product_category: "fashion", quantity: 100, inbound_order_id: 7, stock_after: 148,
      },
    }]);
    // Ni la referencia del cliente (PO-…) ni el nombre del producto.
    expect(JSON.stringify(tracked)).not.toMatch(/PO-1|Zapatilla/);
  });

  it("una pérdida emite stock_loss_recorded y no outbound_order_created", async () => {
    window.localStorage.setItem("trackflow.access_token", jwt({ sub: USER_ID, iat: 1, exp: 4102444800 }));
    fetchMock.mockResolvedValueOnce(
      json({
        id: 9, order_type: "outbound", sku_id: 2, quantity: 3, warehouse: "ZGZ", exit_type: "loss", tracking_number: null,
        user_uuid: USER_ID, created_at: "2026-10-27T09:00:00Z", stock_after: 10,
        sku: { id: 2, sku: "CSM-SRM-030", name: "Sérum", client_name: "GlowLab Cosmetics", category: "cosmetics" },
      }, 201),
    );

    await inventoryApi.registerExit({ sku_id: 2, quantity: 3, exit_type: "loss", tracking_number: null, warehouse: "ZGZ" });

    expect(tracked.map((event) => event.type)).toEqual(["stock_loss_recorded"]);
    expect(tracked[0].properties).toMatchObject({ warehouse: "zaragoza", country: "ES", outbound_order_id: 9, stock_after: 10 });
  });

  it("una salida sin stock emite outbound_order_rejected con el disponible del error de la API", async () => {
    window.localStorage.setItem("trackflow.access_token", jwt({ sub: USER_ID, iat: 1, exp: 4102444800 }));
    fetchMock.mockResolvedValueOnce(json({ detail: "Insufficient stock for SKU 'TEC-EAR-001'. Available: 4, requested: 9." }, 400));
    const sku = { sku: "TEC-EAR-001", client_name: "SoundWave Electronics", category: "electronics" };

    await expect(
      inventoryApi.registerExit({ sku_id: 3, quantity: 9, exit_type: "dispatch", tracking_number: "1Z", warehouse: "LA" }, sku),
    ).rejects.toBeInstanceOf(InventoryApiError);

    expect(tracked).toHaveLength(1);
    expect(tracked[0].type).toBe("outbound_order_rejected");
    expect(tracked[0].properties).toEqual({
      warehouse: "los_angeles", country: "US", client_id: "soundwave_electronics", product_id: "TEC-EAR-001",
      product_category: "electronics", quantity: 9, available_quantity: 4, exit_type: "dispatch",
    });
  });

  it("session_expired se emite una vez por token y solo si había sesión", () => {
    jest.setSystemTime(new Date("2026-10-27T09:00:00.000Z"));
    const token = jwt({ sub: USER_ID, iat: Date.now() / 1000 - 60 });

    trackSessionExpired("client_token_check", null);
    trackSessionExpired("api_401", token);
    trackSessionExpired("api_401", token);

    expect(tracked).toHaveLength(1);
    expect(tracked[0].properties).toEqual({
      detection: "api_401", page_route: "/", session_age_ms: 60_000, had_unsaved_form: false,
    });
  });

  it("api_request_failed: como mucho uno por ruta y tipo de fallo cada 30 s", () => {
    trackApiRequestFailed("/inventory/products/5", "get", { kind: "network" });
    trackApiRequestFailed("/inventory/products/6", "get", { kind: "network" });
    trackApiRequestFailed("/inventory/products/6", "get", { kind: "server_error", status: 503 });
    jest.advanceTimersByTime(30_000);
    trackApiRequestFailed("/inventory/products/6", "get", { kind: "network" });

    expect(tracked.map((event) => event.properties)).toEqual([
      { api_route: "/inventory/products/{id}", http_method: "GET", failure_kind: "network", status_code: null },
      { api_route: "/inventory/products/{id}", http_method: "GET", failure_kind: "server_error", status_code: 503 },
      { api_route: "/inventory/products/{id}", http_method: "GET", failure_kind: "network", status_code: null },
    ]);
  });

  it("frontend_error_captured: sin mensaje, agrupado por fingerprint y con las repeticiones contadas", () => {
    const error = new TypeError("No se pudo leer el candidato Ana García");

    trackFrontendError(error, "window_error");
    trackFrontendError(error, "window_error");
    trackFrontendError(error, "window_error");
    jest.advanceTimersByTime(60_000);
    trackFrontendError(error, "window_error");

    expect(tracked).toHaveLength(2);
    expect(tracked[0].properties).toMatchObject({ error_name: "TypeError", error_source: "window_error", occurrences: 1 });
    expect(tracked[0].properties.error_fingerprint).toMatch(/^[0-9a-f]{16}$/);
    expect(tracked[1].properties.occurrences).toBe(3);
    expect(JSON.stringify(tracked)).not.toContain("Ana");
  });
});
