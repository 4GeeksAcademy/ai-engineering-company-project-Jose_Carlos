#!/bin/sh
# Arranque de la imagen de producción (Dockerfile de la raíz): API, web pública y backoffice.
# Si uno de los tres termina, se paran los demás y el contenedor sale con error, para que
# Docker lo reinicie (restart: unless-stopped / --restart unless-stopped).
set -eu

# Un solo proceso de Uvicorn: TinyDB es un archivo JSON y no admite varios procesos escribiendo.
cd /app
uvicorn services.api.main:app --host 0.0.0.0 --port 8000 --proxy-headers &
api_pid=$!

/opt/serve/node_modules/.bin/serve /app/uis/website/trackflow-web --listen tcp://0.0.0.0:3000 --no-port-switching &
website_pid=$!

cd /app/uis/backoffice
./node_modules/.bin/next start --hostname 0.0.0.0 --port 3001 &
backoffice_pid=$!

trap 'kill "$api_pid" "$website_pid" "$backoffice_pid" 2>/dev/null; exit 0' INT TERM

while kill -0 "$api_pid" 2>/dev/null \
  && kill -0 "$website_pid" 2>/dev/null \
  && kill -0 "$backoffice_pid" 2>/dev/null; do
  sleep 2
done

echo "[start-app.sh] Uno de los procesos se ha detenido; parando el resto."
kill "$api_pid" "$website_pid" "$backoffice_pid" 2>/dev/null || true
exit 1
