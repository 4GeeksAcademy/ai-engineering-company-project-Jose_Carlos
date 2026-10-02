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

export function setToken(token: string) {
  try {
    window.localStorage.setItem(TOKEN_KEY, token);
  } catch {
    // Sin localStorage (modo privado estricto) no hay sesión persistente.
  }
  emitChange();
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
      return issue.msg.replace(/^Value error, /, "");
    default:
      return issue.msg;
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
  return new ApiError(response.status, typeof detail === "string" ? detail : fallback);
}

async function request(path: string, init: RequestInit): Promise<Response> {
  try {
    return await fetch(`${AUTH_API_URL}${path}`, init);
  } catch {
    throw new ApiError(0, "No se pudo conectar con la API. Comprueba que el backend está arrancado.");
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
  const { access_token } = (await response.json()) as TokenResponse;
  setToken(access_token);
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
  return (await response.json()) as Me;
}

export async function updateMyProfile(payload: ProfileUpdatePayload): Promise<Profile> {
  const response = await authFetch("/profiles/me", {
    method: "PUT",
    headers: JSON_HEADERS,
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw await toApiError(response, "No se pudo guardar el perfil.");
  return (await response.json()) as Profile;
}
