"""Carga el histórico de incidencias del CSV del analizador en el gestor de incidencias.

Uso (desde la raíz del repositorio):

    uv run python scripts/seed_incidents.py                 # csv/incidents-trackflow.csv
    uv run python scripts/seed_incidents.py otro.csv
    uv run python scripts/seed_incidents.py --no-embeddings  # no calcula embeddings ahora

Cada fila pasa por la validación compartida del analizador, se transforma al modelo del
gestor (CONTEXT-8) y se valida con las mismas reglas que usa la API. Es idempotente:
ejecutarlo dos veces no duplica incidencias.
"""

import csv
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Al ejecutarlo como script (python scripts/seed_incidents.py) la raíz del repo no está en sys.path.
if __package__ in (None, ""):
    sys.path.insert(0, str(REPO_ROOT))

from packages.shared.incident_model import csv_row_to_incident, validate_incident_fields  # noqa: E402
from packages.shared.incident_validation import validateIncident  # noqa: E402
from services.api import store  # noqa: E402

DEFAULT_CSV = REPO_ROOT / "csv" / "incidents-trackflow.csv"


def seed_incidents(csv_path=DEFAULT_CSV) -> dict:
    """Inserta las filas válidas del CSV. Devuelve {"inserted", "skipped", "invalid"}."""
    inserted = 0
    skipped = 0
    invalid = []

    with open(csv_path, newline="", encoding="utf-8") as file:
        for line_number, row in enumerate(csv.DictReader(file), start=2):
            csv_id = row.get("incident_id") or ""

            # 1. Validación del analizador (misma función que POST /analyze)
            errors = validateIncident(row)

            # 2. Transformación CSV → modelo
            incident = None
            if not errors:
                incident, errors = csv_row_to_incident(row)

            # 3. Validación del modelo (misma función que POST /api/incidents)
            if not errors:
                _, field_errors = validate_incident_fields(incident)
                errors = [error["message"] for error in field_errors]

            if errors:
                invalid.append({"line": line_number, "incident_id": csv_id or "UNKNOWN", "errors": errors})
                continue

            # 4. Idempotencia: por incident_id del CSV y, si no hay, por title + created_at
            if csv_id:
                already_loaded = store.get_seed_key(csv_id) is not None
            else:
                already_loaded = store.find_incident(incident["title"], incident["created_at"]) is not None
            if already_loaded:
                skipped += 1
                continue

            created = store.create_incident(incident)
            if csv_id:
                store.add_seed_key(csv_id, created["id"])
            inserted += 1

    return {"inserted": inserted, "skipped": skipped, "invalid": invalid}


def print_report(result: dict) -> None:
    print("\n========================================")
    print("       INCIDENT SEED REPORT")
    print("========================================")
    print(f"Inserted:                 {result['inserted']}")
    print(f"Skipped (already seeded): {result['skipped']}")
    print(f"Invalid (not inserted):   {len(result['invalid'])}")

    if result["invalid"]:
        print("\nINVALID ROWS")
        print("----------------------------------------")
        for record in result["invalid"]:
            print(f"\nLine {record['line']} · Incident ID: {record['incident_id']}")
            for error in record["errors"]:
                print(f"  - {error}")
    print("\n========================================")


def main() -> None:
    args = sys.argv[1:]
    paths = [arg for arg in args if not arg.startswith("--")]
    csv_path = Path(paths[0]) if paths else DEFAULT_CSV

    if not csv_path.is_file():
        print(f"No se encuentra el CSV: {csv_path}")
        sys.exit(1)

    result = seed_incidents(csv_path)

    if "--no-embeddings" not in args:
        # Los embeddings no forman parte del modelo: si fallan, el seed sigue siendo válido
        # y la API los calcula en la primera búsqueda.
        try:
            from services.api import incident_service

            indexed = incident_service.ensure_index()
            print(f"Embeddings calculados: {indexed}")
        except Exception as error:
            print(f"Aviso: no se pudieron calcular los embeddings ahora ({error}).")

    print_report(result)


if __name__ == "__main__":
    main()
