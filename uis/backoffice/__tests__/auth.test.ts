import { act, renderHook } from "@testing-library/react";
import {
  ApiError,
  changePassword,
  clearToken,
  forgotPassword,
  getMe,
  getNextPath,
  getToken,
  isTokenExpired,
  login,
  register,
  resetPassword,
  setToken,
  updateMyProfile,
  useToken,
} from "../app/lib/auth";
import { AUTH_API_URL } from "../app/lib/constants";

// =========================================================
// UTILIDADES DE PRUEBA
// =========================================================

const TOKEN_KEY = "trackflow.access_token";
const APP_ORIGIN = window.location.origin;

function base64url(value: string): string {
  return btoa(value).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/** JWT con el payload dado. La firma es de relleno: el frontend solo lee `exp`. */
function makeJwt(payload: Record<string, unknown>): string {
  return `${base64url('{"alg":"HS256"}')}.${base64url(JSON.stringify(payload))}.signature`;
}

function nowInSeconds(): number {
  return Math.floor(Date.now() / 1000);
}

function validToken(): string {
  return makeJwt({ sub: "user-1", exp: nowInSeconds() + 600 });
}

function expiredToken(): string {
  return makeJwt({ sub: "user-1", exp: nowInSeconds() - 60 });
}

/** Respuesta mínima de fetch: el código solo usa `ok`, `status` y `json()`. */
function apiResponse(status: number, body?: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => {
      if (body === undefined) throw new SyntaxError("Unexpected end of JSON input");
      return body;
    },
  } as Response;
}

function issue(type: string, field: string, extra: Record<string, unknown> = {}) {
  return { type, loc: ["body", field], msg: "technical message", ...extra };
}

const fetchMock = jest.fn<Promise<Response>, [string, RequestInit]>();

function lastCall() {
  const [url, init] = fetchMock.mock.calls[fetchMock.mock.calls.length - 1];
  return { url, init, body: init.body ? JSON.parse(init.body as string) : undefined };
}

async function rejection(promise: Promise<unknown>): Promise<ApiError> {
  const error = await promise.then(
    () => null,
    (reason: unknown) => reason,
  );
  expect(error).toBeInstanceOf(ApiError);
  return error as ApiError;
}

function setNext(search: string) {
  window.history.replaceState({}, "", `/login${search}`);
}

beforeEach(() => {
  window.localStorage.clear();
  window.history.replaceState({}, "", "/");
  fetchMock.mockReset();
  global.fetch = fetchMock as unknown as typeof fetch;
});

afterEach(() => {
  jest.restoreAllMocks();
});

// =========================================================
// TOKEN EN localStorage
// =========================================================

describe("token storage", () => {
  it("stores, reads and clears the token", () => {
    expect(getToken()).toBeNull();

    expect(setToken("abc")).toBe(true);
    expect(getToken()).toBe("abc");
    expect(window.localStorage.getItem(TOKEN_KEY)).toBe("abc");

    clearToken();
    expect(getToken()).toBeNull();
  });

  it("reports false when the browser refuses to store the token", () => {
    jest.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("denied", "SecurityError");
    });

    expect(setToken("abc")).toBe(false);
  });

  it("treats unreadable storage as having no session", () => {
    jest.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("denied", "SecurityError");
    });

    expect(getToken()).toBeNull();
  });

  it("does not throw when clearing fails", () => {
    jest.spyOn(Storage.prototype, "removeItem").mockImplementation(() => {
      throw new DOMException("denied", "SecurityError");
    });

    expect(() => clearToken()).not.toThrow();
  });
});

describe("useToken", () => {
  it("follows setToken and clearToken", () => {
    const { result } = renderHook(() => useToken());
    expect(result.current).toBeNull();

    act(() => {
      setToken("abc");
    });
    expect(result.current).toBe("abc");

    act(() => clearToken());
    expect(result.current).toBeNull();
  });

  it("picks up a login or logout made in another tab", () => {
    const { result } = renderHook(() => useToken());

    act(() => {
      window.localStorage.setItem(TOKEN_KEY, "from-other-tab");
      window.dispatchEvent(new StorageEvent("storage", { key: TOKEN_KEY }));
    });
    expect(result.current).toBe("from-other-tab");

    act(() => {
      window.localStorage.clear();
      // key === null: la otra pestaña ha vaciado todo el almacenamiento.
      window.dispatchEvent(new StorageEvent("storage", { key: null }));
    });
    expect(result.current).toBeNull();
  });

  it("ignores storage events for other keys and stops listening on unmount", () => {
    const listener = jest.spyOn(Storage.prototype, "getItem");
    const { unmount } = renderHook(() => useToken());
    listener.mockClear();

    act(() => {
      window.dispatchEvent(new StorageEvent("storage", { key: "unrelated" }));
    });
    expect(listener).not.toHaveBeenCalled();

    unmount();
    act(() => {
      window.dispatchEvent(new StorageEvent("storage", { key: TOKEN_KEY }));
    });
    expect(listener).not.toHaveBeenCalled();
  });
});

// =========================================================
// isTokenExpired
// =========================================================

describe("isTokenExpired", () => {
  it("is false while exp is in the future", () => {
    expect(isTokenExpired(validToken())).toBe(false);
  });

  it("is true once exp has passed", () => {
    expect(isTokenExpired(expiredToken())).toBe(true);
  });

  it("is true at the exact second of expiry", () => {
    jest.spyOn(Date, "now").mockReturnValue(1_800_000_000_000);

    expect(isTokenExpired(makeJwt({ exp: 1_800_000_000 }))).toBe(true);
    expect(isTokenExpired(makeJwt({ exp: 1_800_000_001 }))).toBe(false);
  });

  it("decodes base64url payloads (- and _ instead of + and /)", () => {
    const token = makeJwt({ note: "~~~???>>>ÿÿÿ", exp: nowInSeconds() + 600 });
    expect(token.split(".")[1]).toMatch(/[-_]/);

    expect(isTokenExpired(token)).toBe(false);
  });

  it.each([
    ["exp is missing", makeJwt({ sub: "user-1" })],
    ["exp is not a number", makeJwt({ exp: "tomorrow" })],
    ["exp is null", makeJwt({ exp: null })],
    ["the payload is not JSON", `header.${base64url("not json")}.signature`],
    ["the payload is not base64", "header.%%%.signature"],
    ["the token has a single segment", "garbage"],
    ["the token is empty", ""],
  ])("is true when %s", (_case, token) => {
    expect(isTokenExpired(token)).toBe(true);
  });
});

// =========================================================
// getNextPath
// =========================================================

describe("getNextPath", () => {
  it("returns the internal path to go back to", () => {
    setNext("?next=/records/42");

    expect(getNextPath()).toBe("/records/42");
  });

  it("keeps the query string of the internal path", () => {
    setNext(`?next=${encodeURIComponent("/records/42?tab=notes")}`);

    expect(getNextPath()).toBe("/records/42?tab=notes");
  });

  it.each([
    ["there is no next", ""],
    ["next is empty", "?next="],
  ])("falls back to / when %s", (_case, search) => {
    setNext(search);

    expect(getNextPath()).toBe("/");
  });

  it.each([
    ["a protocol-relative URL", "//evil.com"],
    ["a backslash host", "/\\evil.com"],
    ["an absolute URL", "https://evil.com/login"],
    ["a javascript: URL", "javascript:alert(1)"],
    ["a relative path", "records/42"],
    // El navegador elimina tabuladores y saltos de línea: "/\t/evil.com" acaba siendo "//evil.com".
    ["a tab hiding a second slash", "/\t/evil.com"],
    ["a newline hiding a second slash", "/\n/evil.com"],
    ["a carriage return hiding a backslash", "/\r\\evil.com"],
  ])("rejects %s", (_case, next) => {
    setNext(`?next=${encodeURIComponent(next)}`);

    const path = getNextPath();

    expect(path).toBe("/");
    expect(new URL(path, APP_ORIGIN).origin).toBe(APP_ORIGIN);
  });
});

// =========================================================
// login
// =========================================================

describe("login", () => {
  it("posts the credentials and stores the token", async () => {
    fetchMock.mockResolvedValue(apiResponse(200, { access_token: "the-token", token_type: "bearer" }));

    await login("ana@trackflow.com", "s3cret-password");

    const { url, init, body } = lastCall();
    expect(url).toBe(`${AUTH_API_URL}/auth/login`);
    expect(init.method).toBe("POST");
    expect(body).toEqual({ email: "ana@trackflow.com", password: "s3cret-password" });
    expect(getToken()).toBe("the-token");
  });

  it("reports wrong credentials without storing anything", async () => {
    fetchMock.mockResolvedValue(apiResponse(401, { detail: "Incorrect email or password" }));

    const error = await rejection(login("ana@trackflow.com", "wrong"));

    expect(error.status).toBe(401);
    expect(error.message).toBe("Email o contraseña incorrectos.");
    expect(getToken()).toBeNull();
  });

  it("maps validation errors to their fields", async () => {
    fetchMock.mockResolvedValue(apiResponse(422, { detail: [issue("value_error", "email")] }));

    const error = await rejection(login("not-an-email", "x"));

    expect(error.status).toBe(422);
    expect(error.fieldErrors).toEqual({ email: "Introduce un email válido." });
  });

  it("uses its own message instead of the API detail on a server error", async () => {
    fetchMock.mockResolvedValue(apiResponse(500, { detail: "Internal Server Error" }));

    const error = await rejection(login("ana@trackflow.com", "s3cret-password"));

    expect(error.status).toBe(500);
    expect(error.message).toBe("No se pudo iniciar sesión.");
    expect(error.fieldErrors).toEqual({});
  });

  it("copes with an error response that has no JSON body", async () => {
    fetchMock.mockResolvedValue(apiResponse(502));

    const error = await rejection(login("ana@trackflow.com", "s3cret-password"));

    expect(error.status).toBe(502);
    expect(error.message).toBe("No se pudo iniciar sesión.");
  });

  it("reports a connection problem when fetch itself fails", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));

    const error = await rejection(login("ana@trackflow.com", "s3cret-password"));

    expect(error.status).toBe(0);
    expect(error.message).toMatch(/No se pudo conectar/);
  });

  it.each([
    ["the success body is not JSON", apiResponse(200)],
    ["the access token is missing", apiResponse(200, { token_type: "bearer" })],
    ["the access token is not a string", apiResponse(200, { access_token: 123 })],
  ])("fails without storing a token when %s", async (_case, response) => {
    fetchMock.mockResolvedValue(response);

    const error = await rejection(login("ana@trackflow.com", "s3cret-password"));

    expect(error.message).toBe("No se pudo iniciar sesión.");
    expect(getToken()).toBeNull();
  });

  it("tells the user when the browser cannot persist the session", async () => {
    fetchMock.mockResolvedValue(apiResponse(200, { access_token: "the-token" }));
    jest.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("denied", "SecurityError");
    });

    const error = await rejection(login("ana@trackflow.com", "s3cret-password"));

    expect(error.status).toBe(0);
    expect(error.message).toMatch(/no permite guardar la sesión/);
  });
});

// =========================================================
// register
// =========================================================

describe("register", () => {
  const payload = { email: "ana@trackflow.com", password: "s3cret-password", name: "Ana" };

  it("creates the account and then logs in with the same credentials", async () => {
    fetchMock
      .mockResolvedValueOnce(apiResponse(201, { id: "user-1" }))
      .mockResolvedValueOnce(apiResponse(200, { access_token: "the-token" }));

    await register(payload);

    const [createCall, loginCall] = fetchMock.mock.calls;
    expect(createCall[0]).toBe(`${AUTH_API_URL}/users`);
    expect(JSON.parse(createCall[1].body as string)).toEqual(payload);
    expect(loginCall[0]).toBe(`${AUTH_API_URL}/auth/login`);
    expect(JSON.parse(loginCall[1].body as string)).toEqual({
      email: payload.email,
      password: payload.password,
    });
    expect(getToken()).toBe("the-token");
  });

  it("flags the email field when the account already exists and does not log in", async () => {
    fetchMock.mockResolvedValue(apiResponse(409, { detail: "Email already registered" }));

    const error = await rejection(register(payload));

    expect(error.status).toBe(409);
    expect(error.fieldErrors).toEqual({ email: "Ya existe una cuenta con este email." });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(getToken()).toBeNull();
  });

  it("translates each kind of validation error", async () => {
    fetchMock.mockResolvedValue(
      apiResponse(422, {
        detail: [
          issue("string_too_short", "password", { ctx: { min_length: 8 } }),
          issue("string_too_long", "name", { ctx: { max_length: 120 } }),
          issue("missing", "email"),
          issue("value_error", "phone"),
          issue("some_new_pydantic_type", "address"),
        ],
      }),
    );

    const error = await rejection(register(payload));

    expect(error.message).toBe("Revisa los campos marcados.");
    expect(error.fieldErrors).toEqual({
      password: "Debe tener al menos 8 caracteres.",
      name: "Debe tener como máximo 120 caracteres.",
      email: "Este campo es obligatorio.",
      phone: "El valor no es válido.",
      address: "El valor no es válido.",
    });
  });

  it("explains a password over the bcrypt limit and keeps the first error per field", async () => {
    fetchMock.mockResolvedValue(
      apiResponse(422, {
        detail: [
          issue("value_error", "password", { msg: "Value error, Password must be at most 72 bytes" }),
          issue("string_too_short", "password", { ctx: { min_length: 8 } }),
        ],
      }),
    );

    const error = await rejection(register(payload));

    expect(error.fieldErrors).toEqual({ password: "La contraseña es demasiado larga." });
  });

  it("surfaces the login failure when the account was created but login fails", async () => {
    fetchMock
      .mockResolvedValueOnce(apiResponse(201, { id: "user-1" }))
      .mockResolvedValueOnce(apiResponse(500));

    const error = await rejection(register(payload));

    expect(error.message).toBe("No se pudo iniciar sesión.");
    expect(getToken()).toBeNull();
  });
});

// =========================================================
// Rutas protegidas: getMe y updateMyProfile
// =========================================================

describe("getMe", () => {
  const me = { id: "user-1", email: "ana@trackflow.com", role: "user", profile: null };

  it("sends the bearer token and returns the account", async () => {
    const token = validToken();
    setToken(token);
    fetchMock.mockResolvedValue(apiResponse(200, me));

    await expect(getMe()).resolves.toEqual(me);

    const { url, init } = lastCall();
    expect(url).toBe(`${AUTH_API_URL}/auth/me`);
    expect((init.headers as Headers).get("Authorization")).toBe(`Bearer ${token}`);
  });

  it("does not call the API when there is no session", async () => {
    const error = await rejection(getMe());

    expect(error.status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("clears an expired token without calling the API", async () => {
    setToken(expiredToken());

    const error = await rejection(getMe());

    expect(error.status).toBe(401);
    expect(error.message).toMatch(/Tu sesión ha caducado/);
    expect(getToken()).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("closes the session when the API answers 401", async () => {
    setToken(validToken());
    fetchMock.mockResolvedValue(apiResponse(401, { detail: "Could not validate credentials" }));

    const error = await rejection(getMe());

    expect(error.status).toBe(401);
    expect(getToken()).toBeNull();
  });

  it("keeps the session on other errors", async () => {
    const token = validToken();
    setToken(token);
    fetchMock.mockResolvedValue(apiResponse(500));

    const error = await rejection(getMe());

    expect(error.message).toBe("No se pudo cargar tu cuenta.");
    expect(getToken()).toBe(token);
  });

  it("fails cleanly when the success body is not JSON", async () => {
    setToken(validToken());
    fetchMock.mockResolvedValue(apiResponse(200));

    const error = await rejection(getMe());

    expect(error.message).toBe("No se pudo cargar tu cuenta.");
  });
});

describe("updateMyProfile", () => {
  const changes = { name: "Ana B.", phone: null, address: null };

  it("puts the profile with the bearer token and returns the saved one", async () => {
    const saved = { id: "profile-1", user_id: "user-1", ...changes };
    setToken(validToken());
    fetchMock.mockResolvedValue(apiResponse(200, saved));

    await expect(updateMyProfile(changes)).resolves.toEqual(saved);

    const { url, init, body } = lastCall();
    expect(url).toBe(`${AUTH_API_URL}/profiles/me`);
    expect(init.method).toBe("PUT");
    expect(body).toEqual(changes);
    expect((init.headers as Headers).get("Content-Type")).toBe("application/json");
  });

  it("maps a too-long field to its message", async () => {
    setToken(validToken());
    fetchMock.mockResolvedValue(
      apiResponse(422, { detail: [issue("string_too_long", "name", { ctx: { max_length: 120 } })] }),
    );

    const error = await rejection(updateMyProfile(changes));

    expect(error.fieldErrors).toEqual({ name: "Debe tener como máximo 120 caracteres." });
  });

  it("requires a session", async () => {
    const error = await rejection(updateMyProfile(changes));

    expect(error.status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

// =========================================================
// CONTRASEÑAS: RESTABLECIMIENTO Y CAMBIO
// =========================================================

describe("forgotPassword", () => {
  it("posts the email and resolves", async () => {
    fetchMock.mockResolvedValue(apiResponse(200, { message: "ok" }));

    await expect(forgotPassword("ana@trackflow.com")).resolves.toBeUndefined();

    const { url, body } = lastCall();
    expect(url).toBe(`${AUTH_API_URL}/auth/forgot-password`);
    expect(body).toEqual({ email: "ana@trackflow.com" });
  });

  it("flags a malformed email", async () => {
    fetchMock.mockResolvedValue(apiResponse(422, { detail: [issue("value_error", "email")] }));

    const error = await rejection(forgotPassword("not-an-email"));

    expect(error.fieldErrors).toEqual({ email: "Introduce un email válido." });
  });

  it("reports a server error with its own message", async () => {
    fetchMock.mockResolvedValue(apiResponse(500));

    const error = await rejection(forgotPassword("ana@trackflow.com"));

    expect(error.message).toBe("No se pudo enviar la solicitud.");
  });
});

describe("resetPassword", () => {
  it("posts the token and the new password", async () => {
    fetchMock.mockResolvedValue(apiResponse(200, { message: "Password updated" }));

    await expect(resetPassword("reset-token", "brand-new-password")).resolves.toBeUndefined();

    const { url, body } = lastCall();
    expect(url).toBe(`${AUTH_API_URL}/auth/reset-password`);
    expect(body).toEqual({ token: "reset-token", new_password: "brand-new-password" });
  });

  it("explains an invalid, expired or used link", async () => {
    fetchMock.mockResolvedValue(apiResponse(400, { detail: "Invalid, expired or already used reset token" }));

    const error = await rejection(resetPassword("old-token", "brand-new-password"));

    expect(error.status).toBe(400);
    expect(error.message).toBe("El enlace no es válido, ha caducado o ya se ha utilizado.");
  });

  it("flags a too-short new password", async () => {
    fetchMock.mockResolvedValue(
      apiResponse(422, { detail: [issue("string_too_short", "new_password", { ctx: { min_length: 8 } })] }),
    );

    const error = await rejection(resetPassword("reset-token", "short"));

    expect(error.fieldErrors).toEqual({ new_password: "Debe tener al menos 8 caracteres." });
  });
});

describe("changePassword", () => {
  it("posts both passwords with the bearer token", async () => {
    const token = validToken();
    setToken(token);
    fetchMock.mockResolvedValue(apiResponse(200, { message: "Password updated" }));

    await expect(changePassword("s3cret-password", "brand-new-password")).resolves.toBeUndefined();

    const { url, init, body } = lastCall();
    expect(url).toBe(`${AUTH_API_URL}/auth/change-password`);
    expect(body).toEqual({ current_password: "s3cret-password", new_password: "brand-new-password" });
    expect((init.headers as Headers).get("Authorization")).toBe(`Bearer ${token}`);
  });

  it("flags the current password when it is wrong and keeps the session", async () => {
    const token = validToken();
    setToken(token);
    fetchMock.mockResolvedValue(apiResponse(400, { detail: "Current password is incorrect" }));

    const error = await rejection(changePassword("wrong", "brand-new-password"));

    expect(error.status).toBe(400);
    expect(error.fieldErrors).toEqual({ current_password: "La contraseña actual no es correcta." });
    expect(getToken()).toBe(token);
  });

  it("requires a session", async () => {
    const error = await rejection(changePassword("s3cret-password", "brand-new-password"));

    expect(error.status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("reports other failures with its own message", async () => {
    setToken(validToken());
    fetchMock.mockResolvedValue(apiResponse(500));

    const error = await rejection(changePassword("s3cret-password", "brand-new-password"));

    expect(error.message).toBe("No se pudo cambiar la contraseña.");
  });
});
