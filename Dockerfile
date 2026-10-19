# Imagen de PRODUCCIÓN de TrackFlow: una sola imagen autónoma (todo el código va dentro) para
# desplegar en el VPS. El entorno de desarrollo sigue siendo docker-compose.yml (uis/Dockerfile
# y services/Dockerfile, con recarga en caliente).
#
#   docker build -t <usuario>/trackflow:1.0 \
#     --build-arg NEXT_PUBLIC_AUTH_API_URL=http://<IP-o-dominio>:8000 .
#
# Puertos dentro del contenedor:
#   3000 -> website (estático)
#   3002 -> talent-pipeline-tracker (Next.js, `next start`)
#   8000 -> API FastAPI; el backoffice se sirve en /backoffice/ (misma origen que la API)
#
# Los datos (TinyDB y modelo de embeddings) se guardan en /app/data: monta ahí un volumen.

# ---------------------------------------------------------------------------------------------
# Etapa 1: compilar la app Next.js
# ---------------------------------------------------------------------------------------------
FROM node:22-bookworm-slim AS talent-build

WORKDIR /build
COPY uis/talent-pipeline-tracker/package.json uis/talent-pipeline-tracker/package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY uis/talent-pipeline-tracker/ ./

# Next.js escribe las variables NEXT_PUBLIC_* dentro del código del navegador al compilar:
# la URL pública de la API se fija aquí, en `docker build`, no al arrancar el contenedor.
ARG NEXT_PUBLIC_AUTH_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_AUTH_API_URL=$NEXT_PUBLIC_AUTH_API_URL \
    NEXT_TELEMETRY_DISABLED=1
RUN npm run build && npm prune --omit=dev --no-audit --no-fund

# ---------------------------------------------------------------------------------------------
# Etapa 2: imagen final (Node para las webs + Python para la API)
# ---------------------------------------------------------------------------------------------
FROM node:22-bookworm-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.21 /uv /uvx /bin/

# Python 3.13 (el de .python-version) en un entorno propio; uv lo descarga ya compilado.
ENV UV_PYTHON_INSTALL_DIR=/opt/python \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH
COPY services/requirements.txt /tmp/requirements.txt
RUN uv venv --python 3.13 /opt/venv \
 && uv pip install --no-cache -r /tmp/requirements.txt \
 && rm /tmp/requirements.txt

# Servidor de archivos estáticos para el website.
RUN npm install --prefix /opt/serve --no-audit --no-fund serve@14.2.6

WORKDIR /app

# Código de la API: se importa como services.api.main desde /app y usa scripts/ y packages/.
COPY services/ services/
COPY scripts/ scripts/
COPY packages/shared/ packages/shared/
# CSV histórico, para poder ejecutar scripts/seed_incidents.py dentro del contenedor.
COPY csv/ csv/
# Webs estáticas: el backoffice lo sirve la propia API en /backoffice/.
COPY uis/backoffice/ uis/backoffice/
COPY uis/website/trackflow-web/ uis/website/trackflow-web/
# App Next.js ya compilada.
COPY --from=talent-build /build uis/talent-pipeline-tracker/

COPY docker/start-app.sh /usr/local/bin/start-app.sh
RUN sed -i 's/\r$//' /usr/local/bin/start-app.sh && chmod +x /usr/local/bin/start-app.sh

# Datos persistentes fuera del código: TinyDB (+ embeddings, junto al mismo archivo) y la caché
# del modelo de fastembed. Se ejecuta como el usuario sin privilegios `node` (ya existe en la imagen).
ENV PYTHONUNBUFFERED=1 \
    NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    TINYDB_PATH=/app/data/db.json \
    EMBEDDINGS_CACHE_DIR=/app/data/fastembed
RUN mkdir -p /app/data \
 && chown -R node:node /app/data /app/uis/talent-pipeline-tracker/imagenesPerfil
USER node

EXPOSE 3000 3002 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/')"

CMD ["start-app.sh"]
