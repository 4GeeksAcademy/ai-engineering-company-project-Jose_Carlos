# Contenedor del backend (desarrollo): FastAPI servida por Uvicorn con --reload.
# El código llega por bind mount desde docker-compose.yml (services/, scripts/, packages/ y
# uis/backoffice, que la API importa o sirve desde la raíz del repo).
FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.21 /uv /uvx /bin/

WORKDIR /app

# requirements.txt se genera desde uv.lock (ver services/README.md), así el contenedor usa
# exactamente las mismas versiones que `uv sync --frozen` en local.
COPY requirements.txt /tmp/requirements.txt
RUN uv pip install --system --no-cache -r /tmp/requirements.txt

COPY . /app/services

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

CMD ["uvicorn", "services.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload", \
     "--reload-dir", "services", "--reload-dir", "scripts", "--reload-dir", "packages"]
