# Progress

## Fase A — U-A4: referencia de la API en modo FastAPI (2026-10-01)

- **Ejecución**: API arrancada en local (`uvicorn services.api.main:app`, 127.0.0.1, puerto efímero) con el backoffice montado en `/backoffice/`, dirigido con Chrome headless.
- **Dataset**: `csv/incidents-trackflow.csv`, SHA-256 `077e0f4744ea4c8c8ce9d913ba4751b06da12346c282f2d96aeae639a8c4c38c` (el mismo de R4-B); sin cambios antes y después de la ejecución.
- **Resultado** (agregados): 100 filas → 95 válidas, 5 inválidas; categorías RETURN_REQUEST 17, DAMAGE 7, DELAYED_DELIVERY 38, WRONG_ADDRESS 19, LOST_PARCEL 14; estados OPEN 29, CLOSED 52, DISCARDED 14; satisfacción media 3.0577 (en pantalla y en el export: 3.06); 5 registros inválidos, uno por cada tipo de error.
- **Export**: `GET /api/incidents/results/export` → 200 `text/csv`, filas `metric,value` iguales a las derivadas del golden.
- **Comparación**: idéntico al golden R4-B `tests/golden/analyzer_incidents_trackflow.r4b.json` (en la API, en la pantalla del backoffice y en el export). **PASS** (13/13).
- **Observación AS-IS** (no corregida): `/analyze` deja en TEMP una copia del CSV subido; en la ejecución se redirige TEMP a un directorio desechable que se borra al terminar.
- **Reproducir**: `uv sync --frozen` y después `node tests/ui/ua4_dataset_reference.mjs`. El nivel HTTP también está cubierto por `tests/test_analyzer_golden.py` (`uv run --frozen pytest`).
