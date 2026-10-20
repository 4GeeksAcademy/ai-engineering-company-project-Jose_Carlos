#!/bin/sh
# Arranca las dos interfaces en el contenedor, cada una en su puerto y con recarga en caliente:
#   - web pública (estática)                         -> 3000
#   - backoffice (Next.js, con el Talent Pipeline)   -> 3001
# Si una de ellas termina, se para la otra y el contenedor sale con error (así se ve en
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

# --webpack: con WATCHPACK_POLLING=true detecta cambios en bind mounts de Windows/macOS,
# donde los eventos del sistema de archivos no llegan al contenedor.
cd /app/backoffice
./node_modules/.bin/next dev --webpack --hostname 0.0.0.0 --port 3001 &
backoffice_pid=$!

trap 'kill "$website_pid" "$backoffice_pid" 2>/dev/null; exit 0' INT TERM

while kill -0 "$website_pid" 2>/dev/null && kill -0 "$backoffice_pid" 2>/dev/null; do
  sleep 2
done

echo "[start.sh] Una de las interfaces se ha detenido; parando la otra."
kill "$website_pid" "$backoffice_pid" 2>/dev/null || true
exit 1
