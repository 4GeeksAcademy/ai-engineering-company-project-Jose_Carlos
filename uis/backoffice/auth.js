// Sesión JWT del backoffice: token en localStorage, cabecera Authorization: Bearer
// en cada llamada protegida y redirección a login.html si falta, caduca o la API responde 401.
// Se carga en <head> (sin defer) para redirigir antes de pintar la página protegida.
// Las páginas públicas (login.html) lo incluyen con data-public.
(function () {
  const TOKEN_KEY = "trackflow.access_token";
  const LOGIN_PAGE = "login.html";

  function getDefaultApiBaseUrl() {
    if (window.location.hostname.endsWith(".app.github.dev")) {
      const apiHostname = window.location.hostname.replace(
        /-\d+\.app\.github\.dev$/,
        "-8000.app.github.dev",
      );
      return `${window.location.protocol}//${apiHostname}`;
    }

    return "http://localhost:8000";
  }

  // Servido por FastAPI en /backoffice → misma origen; servido aparte (p. ej. :5500) → API base.
  const isSameOriginBackoffice = window.location.pathname.startsWith("/backoffice");
  const API_BASE = window.AUTH_API_BASE_URL || getDefaultApiBaseUrl();

  function apiUrl(path) {
    return isSameOriginBackoffice ? path : `${API_BASE}${path}`;
  }

  function getToken() {
    try {
      return window.localStorage.getItem(TOKEN_KEY);
    } catch {
      return null;
    }
  }

  function setToken(token) {
    try {
      window.localStorage.setItem(TOKEN_KEY, token);
    } catch {
      // Sin localStorage no hay sesión persistente.
    }
  }

  function clearToken() {
    try {
      window.localStorage.removeItem(TOKEN_KEY);
    } catch {
      // Nada que borrar.
    }
  }

  function isTokenExpired(token) {
    try {
      const payload = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
      const { exp } = JSON.parse(atob(payload));
      return typeof exp !== "number" || exp * 1000 <= Date.now();
    } catch {
      return true;
    }
  }

  function hasValidSession() {
    const token = getToken();
    return Boolean(token) && !isTokenExpired(token);
  }

  function redirectToLogin() {
    const current = window.location.pathname.split("/").pop() || "index.html";
    const next = `${current}${window.location.search}`;
    window.location.replace(`${LOGIN_PAGE}?next=${encodeURIComponent(next)}`);
  }

  // Solo páginas del propio backoffice (nombre de archivo .html), nunca otro dominio.
  function getNextPage() {
    const next = new URLSearchParams(window.location.search).get("next");
    return next && /^[\w-]+\.html(\?.*)?$/.test(next) && !next.startsWith(LOGIN_PAGE)
      ? next
      : "index.html";
  }

  function logout() {
    clearToken();
    window.location.replace(LOGIN_PAGE);
  }

  class SessionExpiredError extends Error {}

  /** fetch con el token; en 401 limpia la sesión y redirige al login. */
  async function authFetch(url, options = {}) {
    const token = getToken();
    if (!token || isTokenExpired(token)) {
      clearToken();
      redirectToLogin();
      throw new SessionExpiredError("Tu sesión ha caducado. Inicia sesión de nuevo.");
    }

    const headers = new Headers(options.headers);
    headers.set("Authorization", `Bearer ${token}`);
    const response = await fetch(url, { ...options, headers });

    if (response.status === 401) {
      clearToken();
      redirectToLogin();
      throw new SessionExpiredError("Tu sesión ha caducado. Inicia sesión de nuevo.");
    }
    return response;
  }

  window.TrackflowAuth = {
    apiUrl,
    authFetch,
    clearToken,
    getNextPage,
    getToken,
    hasValidSession,
    logout,
    setToken,
    SessionExpiredError,
  };

  // Guard: las páginas protegidas no se muestran sin una sesión válida.
  if (!document.currentScript.hasAttribute("data-public") && !hasValidSession()) {
    clearToken();
    redirectToLogin();
  }

  // Cualquier botón con data-logout cierra la sesión.
  document.addEventListener("click", (event) => {
    if (event.target.closest("[data-logout]")) logout();
  });
})();
