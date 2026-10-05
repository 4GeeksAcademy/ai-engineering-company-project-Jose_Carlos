# Carpeta `packages`

Esta carpeta contiene **paquetes compartidos** del monorepo: librerías internas, utilidades, tipos, componentes comunes, SDKs, clientes y cualquier código reutilizable por varias aplicaciones/agentes/pipelines.

Cada subcarpeta dentro de `packages/` debería representar **un paquete versionable** (por ejemplo `shared-types`, `ui`, `analytics-sdk`) con su README propio.

- **Propósito principal**: fomentar reutilización y consistencia entre todos los desarrollos de la compañía.
- **Recomendación**: documenta los paquetes que vayas añadiendo, su API pública y cómo se consumen desde `apps/`, `agents/` y `workflows/`.

## `shared/` — lógica de incidencias (Python)

- `incident_validation.py` — reglas de validación de una fila del CSV de incidencias. Las usan `scripts/analyze.py` (y con él `POST /analyze`) y `scripts/seed_incidents.py`.
- `incident_model.py` — dominio del gestor de incidencias: valores permitidos de `category`, `status`, `origin` y `branch`, validación de campos, transiciones de estado y transformación CSV → modelo. Lo usan la API (`services/api/routes/incidents.py`) y `scripts/seed_incidents.py`.

Se importan desde la raíz del repositorio: `from packages.shared.incident_model import ...`.
