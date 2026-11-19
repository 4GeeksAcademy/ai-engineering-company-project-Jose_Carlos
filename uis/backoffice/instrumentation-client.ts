// Next.js ejecuta este archivo en el navegador antes de hidratar la aplicación: es el sitio para
// escuchar los errores globales desde la primera línea (TELEMETRY_PLAN.md, `frontend_error_captured`).
// Los errores de render los captura app/error.tsx; aquí llegan el resto (manejadores de eventos,
// temporizadores, promesas sin `catch`).

import { trackFrontendError } from "./app/lib/telemetry-events";

try {
  window.addEventListener("error", (event) => {
    // Un recurso que no carga (imagen, script) también dispara "error", pero sin `error`.
    if (event.error !== undefined || event.message) trackFrontendError(event.error ?? new Error(), "window_error");
  });
  window.addEventListener("unhandledrejection", (event) => trackFrontendError(event.reason, "unhandled_rejection"));
} catch {
  // La telemetría nunca impide arrancar la aplicación.
}
