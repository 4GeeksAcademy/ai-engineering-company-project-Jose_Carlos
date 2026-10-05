# Carpeta `scripts`

Esta carpeta contiene **scripts auxiliares** del monorepo: automatizaciones de desarrollo, utilidades de mantenimiento, tareas repetitivas (setup, lint, migraciones, generación de datos, etc.) y tooling interno.

- **Propósito principal**: agrupar herramientas de soporte que no pertenecen a una app/agente/pipeline específico, pero facilitan el trabajo del equipo.
- **Recomendación**: documenta cada script (qué hace, parámetros, requisitos, ejemplos de uso) y procura que sean reproducibles (y seguros) en distintos entornos.

## Scripts

Se ejecutan desde la raíz del repositorio.

- `analyze.py` — analizador del CSV de incidencias (`uv run python scripts/analyze.py`). Sus reglas de validación están en `packages/shared/incident_validation.py`.
- `seed_incidents.py` — carga el histórico `csv/incidents-trackflow.csv` en el gestor de incidencias (`uv run python scripts/seed_incidents.py`). Valida cada fila con las reglas del analizador, la transforma al modelo del gestor (`packages/shared/incident_model.py`), informa en consola de las filas inválidas sin insertarlas y no duplica registros si se ejecuta varias veces. Con `--no-embeddings` no calcula los embeddings en ese momento (la API los calcula en la primera búsqueda).
