"""Carga el histórico de incidencias del CSV del analizador en el gestor de incidencias.

Uso (desde la raíz del repositorio):

    uv run python scripts/seed_incidents.py                 # csv/incidents-trackflow.csv
    uv run python scripts/seed_incidents.py otro.csv
    uv run python scripts/seed_incidents.py --no-embeddings  # no calcula embeddings ahora
    uv run python scripts/seed_incidents.py --strict         # código 2 si fallan los embeddings

Termina con código 1 si el CSV no se puede leer, no es el del analizador o no aporta
ninguna fila válida.

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
from packages.shared.incident_validation import requiredFields, validateIncident  # noqa: E402
from services.api import store  # noqa: E402

DEFAULT_CSV = REPO_ROOT / "csv" / "incidents-trackflow.csv"

# Códigos de salida: 0 correcto, 1 no se ha podido cargar, 2 cargado pero sin embeddings
# (solo con --strict; sin esa opción un fallo de embeddings es un aviso).
EXIT_FAILED = 1
EXIT_EMBEDDINGS_FAILED = 2


class SeedError(Exception):
    """El CSV no se puede cargar (no es el fichero del analizador)."""


def seed_incidents(csv_path=DEFAULT_CSV) -> dict:
    """Inserta las filas válidas del CSV. Devuelve {"inserted", "skipped", "invalid"}.

    Lanza SeedError, antes de insertar nada, si al CSV le faltan columnas del analizador.
    """
    inserted = 0
    skipped = 0
    invalid = []

    with open(csv_path, newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)

        # Con otra cabecera todas las filas serían "inválidas" y el seed parecería correcto.
        missing = [field for field in requiredFields if field not in (reader.fieldnames or [])]
        if missing:
            raise SeedError(f"Al CSV le faltan columnas obligatorias: {', '.join(missing)}.")

        for line_number, row in enumerate(reader, start=2):
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
        print(f"No se encuentra el CSV: {csv_path}", file=sys.stderr)
        sys.exit(EXIT_FAILED)

    try:
        result = seed_incidents(csv_path)
    except SeedError as error:
        print(f"No se ha cargado nada. {error}", file=sys.stderr)
        sys.exit(EXIT_FAILED)
    except UnicodeDecodeError:
        print(
            f"El CSV {csv_path} no está codificado en UTF-8. "
            "Las filas anteriores al error ya se han insertado; vuelve a ejecutar el seed "
            "con el archivo corregido (no duplica registros).",
            file=sys.stderr,
        )
        sys.exit(EXIT_FAILED)
    except csv.Error as error:
        print(
            f"El CSV {csv_path} está mal formado ({error}). "
            "Las filas anteriores al error ya se han insertado; vuelve a ejecutar el seed "
            "con el archivo corregido (no duplica registros).",
            file=sys.stderr,
        )
        sys.exit(EXIT_FAILED)

    embeddings_failed = False
    if "--no-embeddings" not in args:
        from services.api import incident_service
        from services.api.embeddings import EmbeddingsUnavailable

        # Los embeddings no forman parte del modelo: si fallan, las incidencias ya están
        # cargadas y la API los calcula en la primera búsqueda.
        try:
            indexed = incident_service.ensure_index()
            print(f"Embeddings calculados: {indexed}")
        except EmbeddingsUnavailable:
            embeddings_failed = True
            print(
                "Aviso: no se pudieron calcular los embeddings. Las incidencias están cargadas "
                "y la API los calculará en la primera búsqueda.",
                file=sys.stderr,
            )

    print_report(result)

    if result["inserted"] == 0 and result["skipped"] == 0:
        print("Ninguna fila del CSV era válida: no se ha cargado ninguna incidencia.", file=sys.stderr)
        sys.exit(EXIT_FAILED)
    if embeddings_failed and "--strict" in args:
        sys.exit(EXIT_EMBEDDINGS_FAILED)


if __name__ == "__main__":
    main()
