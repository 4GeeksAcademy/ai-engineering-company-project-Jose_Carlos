"use client";

import { useSyncExternalStore } from "react";
import { AUTH_API_URL } from "./constants";
import { Me, Profile, ProfileUpdatePayload, RegisterPayload, TokenResponse } from "./types";

// =========================================================
// TOKEN EN localStorage
// =========================================================

const TOKEN_KEY = "trackflow.access_token";
const listeners = new Set<() => void>();

function emitChange() {
  listeners.forEach((listener) => listener());
}

export function getToken(): string | null {
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

/** Guarda el token. Devuelve false si el navegador no deja (modo privado estricto). */
export function setToken(token: string): boolean {
  let stored = true;
  try {
    window.localStorage.setItem(TOKEN_KEY, token);
  } catch {
    // Sin localStorage no hay sesión persistente: quien llama avisa al usuario.
    stored = false;
  }
  emitChange();
  return stored;
}

export function clearToken() {
  try {
    window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    // Nada que borrar.
  }
  emitChange();
}

function subscribe(listener: () => void) {
  // "storage" avisa de cambios hechos en otras pestañas (login/logout en paralelo).
  const onStorage = (event: StorageEvent) => {
    if (event.key === null || event.key === TOKEN_KEY) listener();
  };
  listeners.add(listener);
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", onStorage);
  };
}

/**
 * Token actual. `undefined` durante el render en servidor/hidratación (aún no se
 * puede leer localStorage), `null` si no hay sesión.
 */
export function useToken(): string | null | undefined {
  return useSyncExternalStore(subscribe, getToken, () => undefined);
}

/** true si el token no es un JWT legible o su `exp` ya ha pasado. */
export function isTokenExpired(token: string): boolean {
  try {
    const payload = token.split(".")[1];
    const json = atob(payload.replace(/-/g, "+").replace(/_/g, "/"));
    const { exp } = JSON.parse(json) as { exp?: number };
    return typeof exp !== "number" || exp * 1000 <= Date.now();
  } catch {
    return true;
  }
}

/** Ruta interna a la que volver tras el login (`?next=`), evitando redirecciones abiertas. */
export function getNextPath(): string {
  const next = new URLSearchParams(window.location.search).get("next");
  // Solo rutas internas: "//host" o "/\host" llevarían a otro dominio.
  return next && /^\/(?![/\\])/.test(next) ? next : "/";
}

// =========================================================
// ERRORES DE LA API
// =========================================================

export type FieldErrors = Partial<Record<string, string>>;

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public fieldErrors: FieldErrors = {},
  ) {
    super(message);
  }
}

type ValidationIssue = {
  type: string;
  loc: Array<string | number>;
  msg: string;
  ctx?: Record<string, unknown>;
};

function translateIssue(issue: ValidationIssue): string {
  switch (issue.type) {
    case "string_too_short":
      return `Debe tener al menos ${issue.ctx?.min_length} caracteres.`;
    case "string_too_long":
      return `Debe tener como máximo ${issue.ctx?.max_length} caracteres.`;
    case "missing":
      return "Este campo es obligatorio.";
    case "value_error":
      if (issue.loc.at(-1) === "email") return "Introduce un email válido.";
      if (issue.msg.includes("72 bytes")) return "La contraseña es demasiado larga.";
      return "El valor no es válido.";
    default:
      // El mensaje de la API llega en inglés técnico: no se muestra.
      return "El valor no es válido.";
  }
}

async function toApiError(response: Response, fallback: string): Promise<ApiError> {
  const body = (await response.json().catch(() => null)) as { detail?: unknown } | null;
  const detail = body?.detail;

  if (Array.isArray(detail)) {
    const fieldErrors: FieldErrors = {};
    for (const issue of detail as ValidationIssue[]) {
      const field = String(issue.loc.at(-1));
      fieldErrors[field] ??= translateIssue(issue);
    }
    return new ApiError(response.status, "Revisa los campos marcados.", fieldErrors);
  }
  // El `detail` de texto de la API (en inglés) no se muestra: cada llamada da su propio mensaje.
  return new ApiError(response.status, fallback);
}

const REQUEST_TIMEOUT_MS = 15000;

async function request(path: string, init: RequestInit): Promise<Response> {
  try {
    return await fetch(`${AUTH_API_URL}${path}`, {
      ...init,
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });
  } catch {
    // Sin conexión, CORS o tiempo de espera agotado.
    throw new ApiError(0, "No se pudo conectar con el servidor. Comprueba tu conexión e inténtalo de nuevo.");
  }
}

/** Cuerpo JSON de una respuesta correcta; si no se puede leer, error con el mensaje dado. */
async function readJson<T>(response: Response, fallback: string): Promise<T> {
  try {
    return (await response.json()) as T;
  } catch {
    throw new ApiError(response.status, fallback);
  }
}

/**
 * Llamada a una ruta protegida: adjunta `Authorization: Bearer <token>`. Si no hay
 * token, ha caducado o la API responde 401, limpia la sesión (el guard redirige a /login).
 */
async function authFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const token = getToken();
  if (!token || isTokenExpired(token)) {
    clearToken();
    throw new ApiError(401, "Tu sesión ha caducado. Inicia sesión de nuevo.");
  }

  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${token}`);
  const response = await request(path, { ...init, headers });

  if (response.status === 401) {
    clearToken();
    throw new ApiError(401, "Tu sesión ha caducado. Inicia sesión de nuevo.");
  }
  return response;
}

const JSON_HEADERS = { "Content-Type": "application/json" };

// =========================================================
// ENDPOINTS DE AUTENTICACIÓN Y CUENTA
// =========================================================

/** POST /auth/login: guarda el token en localStorage si las credenciales son válidas. */
export async function login(email: string, password: string): Promise<void> {
  const response = await request("/auth/login", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ email, password }),
  });
  if (response.status === 401) {
    throw new ApiError(401, "Email o contraseña incorrectos.");
  }
  if (!response.ok) {
    throw await toApiError(response, "No se pudo iniciar sesión.");
  }
  const { access_token } = await readJson<TokenResponse>(response, "No se pudo iniciar sesión.");
  if (typeof access_token !== "string") {
    throw new ApiError(response.status, "No se pudo iniciar sesión.");
  }
  if (!setToken(access_token)) {
    throw new ApiError(
      0,
      "Tu navegador no permite guardar la sesión. Sal del modo privado o permite el almacenamiento para este sitio.",
    );
  }
}

/** POST /users y después POST /auth/login con las mismas credenciales. */
export async function register(payload: RegisterPayload): Promise<void> {
  const response = await request("/users", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(payload),
  });
  if (response.status === 409) {
    throw new ApiError(409, "Revisa los campos marcados.", {
      email: "Ya existe una cuenta con este email.",
    });
  }
  if (!response.ok) {
    throw await toApiError(response, "No se pudo crear la cuenta.");
  }
  await login(payload.email, payload.password);
}

export async function getMe(): Promise<Me> {
  const response = await authFetch("/auth/me");
  if (!response.ok) throw await toApiError(response, "No se pudo cargar tu cuenta.");
  return readJson<Me>(response, "No se pudo cargar tu cuenta.");
}

export async function updateMyProfile(payload: ProfileUpdatePayload): Promise<Profile> {
  const response = await authFetch("/profiles/me", {
    method: "PUT",
    headers: JSON_HEADERS,
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw await toApiError(response, "No se pudo guardar el perfil.");
  return readJson<Profile>(response, "No se pudo guardar el perfil.");
}

// =========================================================
// CONTRASEÑAS: RESTABLECIMIENTO Y CAMBIO
// =========================================================

/** POST /auth/forgot-password: la API responde 200 exista o no el email. */
export async function forgotPassword(email: string): Promise<void> {
  const response = await request("/auth/forgot-password", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ email }),
  });
  if (!response.ok) throw await toApiError(response, "No se pudo enviar la solicitud.");
}

/** POST /auth/reset-password con el token del enlace recibido por correo. */
export async function resetPassword(token: string, newPassword: string): Promise<void> {
  const response = await request("/auth/reset-password", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ token, new_password: newPassword }),
  });
  if (response.status === 400) {
    throw new ApiError(400, "El enlace no es válido, ha caducado o ya se ha utilizado.");
  }
  if (!response.ok) throw await toApiError(response, "No se pudo restablecer la contraseña.");
}

/** POST /auth/change-password (requiere sesión). */
export async function changePassword(currentPassword: string, newPassword: string): Promise<void> {
  const response = await authFetch("/auth/change-password", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
  });
  if (response.status === 400) {
    throw new ApiError(400, "Revisa los campos marcados.", {
      current_password: "La contraseña actual no es correcta.",
    });
  }
  if (!response.ok) throw await toApiError(response, "No se pudo cambiar la contraseña.");
}
