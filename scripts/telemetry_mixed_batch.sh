#!/usr/bin/env bash
# Prueba manual del rechazo individual de POST /telemetry/events (hito 16, Fase 3).
#
# Envía con curl un lote de 4 eventos —2 válidos, 1 con el envelope roto (eventId que no es un
# UUID) y 1 que se sale de su allowlist (lleva un email en properties)— y muestra la respuesta.
# Lo esperado: HTTP 200 y {"received":4,"stored":2,"rejected":2}.
#
#   scripts/telemetry_mixed_batch.sh                                   # API local (uvicorn :8000)
#   scripts/telemetry_mixed_batch.sh http://127.0.0.1:8000/telemetry/events
#
# Imprime los eventId de los dos válidos para buscarlos después en Supabase:
#   select id, event_type, timestamp, tags from telemetry_events where id in ('<id1>', '<id2>');
set -euo pipefail

ENDPOINT="${1:-http://localhost:8000/telemetry/events}"

uuid4() {
  if command -v uuidgen >/dev/null 2>&1; then
    uuidgen | tr '[:upper:]' '[:lower:]'
  else
    python -c "import uuid; print(uuid.uuid4())"
  fi
}

now="$(date -u +%Y-%m-%dT%H:%M:%S.000Z)"
session="$(uuid4)"
valid_1="$(uuid4)"
valid_2="$(uuid4)"

page_viewed() { # $1 = eventId, $2 = properties
  printf '{"eventId":"%s","timestamp":"%s","sessionId":"%s","userId":null,"event_type":"page_viewed","schemaVersion":"1.0.0","requestId":"%s","source":"backoffice_web","environment":"development","properties":%s}' \
    "$1" "$now" "$session" "$(uuid4)" "$2"
}

properties='{"page_route":"/inventory/products","section":"inventory","previous_route":null}'
leaky='{"page_route":"/inventory/products","section":"inventory","previous_route":null,"email":"ana@trackflow.com"}'

body="{\"events\":[$(page_viewed "$valid_1" "$properties"),$(page_viewed "no-es-un-uuid" "$properties"),$(page_viewed "$(uuid4)" "$leaky"),$(page_viewed "$valid_2" "$properties")]}"

echo "POST $ENDPOINT (4 eventos: 2 válidos, 1 envelope roto, 1 fuera de su allowlist)"
curl --silent --show-error --write-out '\nHTTP %{http_code}\n' \
  --header 'Content-Type: application/json' --data "$body" "$ENDPOINT"
echo "Válidos (deberían estar en telemetry_events): $valid_1 $valid_2"
