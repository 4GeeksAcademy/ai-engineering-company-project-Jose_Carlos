// TelemetryService del backoffice (TELEMETRY_PLAN.md, hito 15).
//
// Todo el tracking del backoffice pasa por `track(eventType, properties)`. Nadie más hace fetch a la
// telemetría. El servicio:
//
// - Completa el Event Envelope: eventId, timestamp (el de la captura, no el del envío), sessionId,
//   userId, schemaVersion, requestId, source y environment. Quien llama solo pasa el tipo y sus
//   propiedades.
// - Acumula los eventos en una cola en memoria y los envía en lotes `{"events": [...]}`: a los 10 s
//   del primer evento pendiente o en cuanto hay 20, lo que ocurra antes. Nunca uno a uno.
// - Reintenta un lote fallido hasta 3 veces con espera exponencial (1 s, 2 s, 4 s) y después lo
//   descarta: la telemetría no es crítica y nunca bloquea la aplicación.
// - Cuando la pestaña se oculta o se cierra, vacía la cola con navigator.sendBeacon, que el navegador
//   entrega aunque la página se esté destruyendo.
//
// El destino es NEXT_PUBLIC_TELEMETRY_ENDPOINT: hoy el stub de la API, mañana el endpoint con
// persistencia, sin tocar este archivo. Sin la variable, la telemetría queda desactivada.

import { getToken } from "./auth";
import { TELEMETRY_SCHEMA_VERSIONS, TelemetryEventType } from "./telemetry-schema";

export const BATCH_SIZE = 20;
export const FLUSH_INTERVAL_MS = 10_000;
export const MAX_RETRIES = 3;
export const RETRY_BASE_MS = 1_000;

const SESSION_KEY = "trackflow.telemetry.session_id";
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

export type HideReason = "hidden" | "pagehide";

export type TelemetryEnvelope = {
  eventId: string;
  timestamp: string;
  sessionId: string | null;
  userId: string | null;
  event_type: TelemetryEventType;
  schemaVersion: string;
  requestId: string;
  source: "backoffice_web";
  environment: "development" | "test" | "production";
  properties: Record<string, unknown>;
};

// ---------------------------------------------------------------- identificadores

/** UUID v4. `crypto.randomUUID` solo existe en contextos seguros (https o localhost). */
export function uuidv4(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

/** Sesión de telemetría de esta pestaña: se crea al primer uso y cambia en cada login y logout. */
export function telemetrySessionId(): string | null {
  try {
    let id = window.sessionStorage.getItem(SESSION_KEY);
    if (!id || !UUID.test(id)) {
      id = uuidv4();
      window.sessionStorage.setItem(SESSION_KEY, id);
    }
    return id;
  } catch {
    // Sin sessionStorage (modo privado estricto): los eventos van sin sesión.
    return null;
  }
}

/** Empieza una sesión nueva: se llama al iniciar y al cerrar sesión. */
export function startTelemetrySession(): void {
  try {
    window.sessionStorage.setItem(SESSION_KEY, uuidv4());
  } catch {
    // Nada que rotar.
  }
}

type TokenClaims = { sub?: unknown; iat?: unknown };

/** Claims del JWT guardado, aunque haya caducado (lo justo para `userId` y la edad de la sesión). */
export function tokenClaims(token: string | null = getToken()): TokenClaims | null {
  if (!token) return null;
  try {
    const payload = token.split(".")[1];
    return JSON.parse(atob(payload.replace(/-/g, "+").replace(/_/g, "/"))) as TokenClaims;
  } catch {
    return null;
  }
}

/** Usuario autenticado: el `sub` del JWT es su id en TinyDB. Nunca su email ni su nombre. */
function currentUserId(): string | null {
  const sub = tokenClaims()?.sub;
  return typeof sub === "string" && UUID.test(sub) ? sub : null;
}

function environment(): TelemetryEnvelope["environment"] {
  if (process.env.NODE_ENV === "production") return "production";
  return process.env.NODE_ENV === "test" ? "test" : "development";
}

function endpoint(): string | null {
  return process.env.NEXT_PUBLIC_TELEMETRY_ENDPOINT?.trim() || null;
}

// ---------------------------------------------------------------- servicio

export class TelemetryService {
  private queue: TelemetryEnvelope[] = [];
  private timer: ReturnType<typeof setTimeout> | null = null;
  // Lotes esperando su reintento: si la pestaña se cierra, se mandan con sendBeacon.
  private retrying = new Map<ReturnType<typeof setTimeout>, TelemetryEnvelope[]>();
  private hideHooks = new Set<(reason: HideReason) => void>();
  private installed = false;
  private warned = false;

  constructor(private readonly getEndpoint: () => string | null = endpoint) {}

  track(eventType: TelemetryEventType, properties: Record<string, unknown>, options: { requestId?: string | null } = {}): void {
    if (typeof window === "undefined") return;
    if (!this.getEndpoint()) {
      if (!this.warned) console.warn("Telemetría desactivada: falta NEXT_PUBLIC_TELEMETRY_ENDPOINT.");
      this.warned = true;
      return;
    }
    this.install();
    this.queue.push({
      eventId: uuidv4(),
      timestamp: new Date().toISOString(),
      sessionId: telemetrySessionId(),
      userId: currentUserId(),
      event_type: eventType,
      schemaVersion: TELEMETRY_SCHEMA_VERSIONS[eventType],
      // Solo la capa de API pasa el X-Request-Id de su llamada; si no, cada evento lleva uno nuevo.
      requestId: options.requestId && UUID.test(options.requestId) ? options.requestId : uuidv4(),
      source: "backoffice_web",
      environment: environment(),
      properties,
    });
    if (this.queue.length >= BATCH_SIZE) this.flush();
    else if (this.timer === null) this.timer = setTimeout(() => this.flush(), FLUSH_INTERVAL_MS);
  }

  /** Envía lo pendiente por fetch, en lotes de como mucho BATCH_SIZE. */
  flush(): void {
    this.clearTimer();
    while (this.queue.length) this.send(this.queue.splice(0, BATCH_SIZE), 0);
  }

  /**
   * Registra algo que hay que hacer justo antes del flush por ocultarse la pestaña (p. ej. Web
   * Vitals). `reason` distingue ocultarla (`hidden`: puede volver) de abandonarla (`pagehide`).
   */
  onHide(hook: (reason: HideReason) => void): () => void {
    this.hideHooks.add(hook);
    return () => this.hideHooks.delete(hook);
  }

  /** Flush por sendBeacon: la pestaña se oculta o se cierra. */
  flushOnHide(reason: HideReason = "hidden"): void {
    for (const hook of [...this.hideHooks]) {
      try {
        hook(reason);
      } catch {
        // Un hook roto no impide enviar el resto.
      }
    }
    this.clearTimer();
    const pending = [...this.queue.splice(0)];
    for (const [timer, batch] of this.retrying) {
      clearTimeout(timer);
      pending.push(...batch);
    }
    this.retrying.clear();
    for (let i = 0; i < pending.length; i += BATCH_SIZE) this.beacon(pending.slice(i, i + BATCH_SIZE));
  }

  /** Escucha `visibilitychange` (y `pagehide`, que Safari dispara al cerrar) una sola vez. */
  install(): void {
    if (this.installed || typeof window === "undefined") return;
    this.installed = true;
    // En `window` y no en `document`: el evento sube de document a window, así que este listener
    // corre después de los de web-vitals (en document), que publican ahí el CLS y el INP finales.
    window.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "hidden") this.flushOnHide("hidden");
    });
    window.addEventListener("pagehide", () => this.flushOnHide("pagehide"));
  }

  private clearTimer() {
    if (this.timer !== null) clearTimeout(this.timer);
    this.timer = null;
  }

  private body(batch: TelemetryEnvelope[]) {
    return JSON.stringify({ events: batch });
  }

  private async send(batch: TelemetryEnvelope[], attempt: number): Promise<void> {
    const url = this.getEndpoint();
    if (!url) return;
    let retry = false;
    try {
      const response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: this.body(batch),
        // keepalive: si el usuario navega mientras sale el lote, la petición sigue viva.
        keepalive: true,
      });
      // Un 4xx (lote mal formado) no se arregla reintentando; un 5xx o un 429, quizá sí.
      retry = response.status >= 500 || response.status === 429;
    } catch {
      retry = true; // red caída, CORS o servidor parado
    }
    if (!retry) return;
    if (attempt >= MAX_RETRIES) return; // descartado: la telemetría no bloquea la app
    const timer = setTimeout(() => {
      this.retrying.delete(timer);
      this.send(batch, attempt + 1);
    }, RETRY_BASE_MS * 2 ** attempt);
    this.retrying.set(timer, batch);
  }

  private beacon(batch: TelemetryEnvelope[]) {
    const url = this.getEndpoint();
    if (!url) return;
    // text/plain: es una petición "simple" para CORS. Con application/json el navegador necesitaría
    // una petición previa (preflight) que sendBeacon no puede hacer, y la descartaría.
    const blob = new Blob([this.body(batch)], { type: "text/plain;charset=UTF-8" });
    const queued = typeof navigator !== "undefined" && typeof navigator.sendBeacon === "function" && navigator.sendBeacon(url, blob);
    // sendBeacon rechaza cuerpos de más de ~64 KB o si su cola está llena: último intento con keepalive.
    if (!queued) this.send(batch, MAX_RETRIES);
  }
}

export const telemetryService = new TelemetryService();

/**
 * Única función pública de tracking. `eventType` es el `event_type` del envelope y `properties` debe
 * cumplir su allowlist de event-schemas.json. `options.requestId` solo lo usa la capa de API
 * (lib/*.ts) para correlacionar el evento con su llamada HTTP; los componentes nunca lo pasan.
 */
export function track(eventType: TelemetryEventType, properties: Record<string, unknown>, options?: { requestId?: string | null }): void {
  try {
    telemetryService.track(eventType, properties, options);
  } catch {
    // La telemetría nunca rompe una pantalla.
  }
}
