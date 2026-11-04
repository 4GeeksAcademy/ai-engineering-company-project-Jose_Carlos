// Eventos que captura el backoffice y versión de su esquema (TELEMETRY_PLAN.md, event-schemas.json).
//
// Es la constante compartida de la que el TelemetryService saca el `schemaVersion` de cada evento:
// ningún componente lo pasa a mano. tests/telemetry/test_frontend_contract.py comprueba que estas
// versiones coinciden con las de event-schemas.json, así que un cambio de esquema que no se refleje
// aquí rompe los tests y no llega a producción.
//
// Los eventos que solo ve el servidor (stock_threshold_triggered, inventory_discrepancy_detected y
// direct_stock_edit_rejected) los emite la API y no están en esta lista.

export const TELEMETRY_SCHEMA_VERSIONS = {
  // Obligatorios del BRIEFING, capturados al recibir la respuesta de la API.
  inbound_order_created: "1.0.0",
  outbound_order_created: "1.0.0",
  // Oportunidades priorizadas (hito 15).
  stock_loss_recorded: "1.0.0",
  outbound_order_rejected: "1.0.0",
  order_form_abandoned: "1.0.0",
  login_failed: "2.0.0",
  session_expired: "1.0.0",
  page_viewed: "1.0.0",
  page_load_recorded: "1.0.0",
  frontend_error_captured: "1.0.0",
  api_request_failed: "1.0.0",
} as const;

export type TelemetryEventType = keyof typeof TELEMETRY_SCHEMA_VERSIONS;
