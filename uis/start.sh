#!/bin/sh
# Arranca las tres interfaces en el contenedor, cada una en su puerto y con recarga en caliente:
#   - website (estático)              -> 3000
#   - backoffice (estático)           -> 3001
#   - talent-pipeline-tracker (Next)  -> 3002
# Si una de ellas termina, se paran las demás y el contenedor sale con error (así se ve en
# `docker compose ps` / logs en vez de quedarse medio arrancado).
set -eu

# Comprobación de red entre contenedores: el backend se alcanza por su nombre de servicio
# (API_INTERNAL_URL=http://backend:8000), nunca por localhost. No bloquea el arranque.
if [ -n "${API_INTERNAL_URL:-}" ]; then
  i=0
  until wget -q -O /dev/null "$API_INTERNAL_URL/"; do
    i=$((i + 1))
    if [ "$i" -ge 30 ]; then
      echo "[start.sh] Aviso: $API_INTERNAL_URL no responde; las interfaces arrancan igualmente."
      break
    fi
    sleep 2
  done
  if [ "$i" -lt 30 ]; then
    echo "[start.sh] Backend accesible en $API_INTERNAL_URL"
  fi
fi

# --files admite una lista separada por comas (por eso no se usan llaves {html,css,js}).
/opt/uis/website/node_modules/.bin/browser-sync start \
  --server /app/website/trackflow-web \
  --files "/app/website/trackflow-web/**/*.html,/app/website/trackflow-web/**/*.css,/app/website/trackflow-web/**/*.js" \
  --port 3000 --no-open --no-ui --no-notify &
website_pid=$!

# El backoffice se sirve en la raíz (no bajo /backoffice), así sus scripts llaman a la API en
# http://localhost:8000 desde el navegador. --ss /app resuelve el enlace relativo
# ../website/trackflow-web/index.html del logo.
/opt/uis/backoffice/node_modules/.bin/browser-sync start \
  --server /app/backoffice --ss /app \
  --files "/app/backoffice/**/*.html,/app/backoffice/**/*.css,/app/backoffice/**/*.js" \
  --ignore "**/node_modules/**" \
  --port 3001 --no-open --no-ui --no-notify &
backoffice_pid=$!

# --webpack: con WATCHPACK_POLLING=true detecta cambios en bind mounts de Windows/macOS,
# donde los eventos del sistema de archivos no llegan al contenedor.
cd /app/talent-pipeline-tracker
./node_modules/.bin/next dev --webpack --hostname 0.0.0.0 --port 3002 &
talent_pid=$!

trap 'kill "$website_pid" "$backoffice_pid" "$talent_pid" 2>/dev/null; exit 0' INT TERM

while kill -0 "$website_pid" 2>/dev/null \
  && kill -0 "$backoffice_pid" 2>/dev/null \
  && kill -0 "$talent_pid" 2>/dev/null; do
  sleep 2
done

echo "[start.sh] Una de las interfaces se ha detenido; parando el resto."
kill "$website_pid" "$backoffice_pid" "$talent_pid" 2>/dev/null || true
exit 1
