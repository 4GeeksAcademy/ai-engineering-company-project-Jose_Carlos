import csv
import sys
from pathlib import Path

# Al ejecutarlo como script (python scripts/analyze.py) la raíz del repo no está en sys.path.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Las reglas de validación viven en packages/shared/ (compartidas con el seed del gestor).
from packages.shared.incident_validation import (  # noqa: E402,F401
    requiredFields,
    validCarriers,
    validCategories,
    validCountries,
    validStatuses,
    validateIncident,
)


# =========================================================
# ANÁLISIS DEL CSV
# =========================================================

def analyzeCsv(filePath):

    filasValidas = 0
    filasInvalidas = 0
    categoryCount = {}
    statusCount = {}
    total = 0
    count = 0
    listaErrores = []

    with open(filePath, newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)

        for row in reader:

            errors = validateIncident(row)

            if not errors:
                filasValidas += 1

                category = row["category"]
                status = row["status"]

                # Cuenta de categoría
                if category in categoryCount:
                    categoryCount[category] += 1
                else:
                    categoryCount[category] = 1
                
                # Cuenta de status
                if status in statusCount:
                    statusCount[status] += 1
                else:
                    statusCount[status] = 1

                # Media de satisfacción
                if row.get("status") == 'CLOSED' and row.get("satisfaction_score"):
                    total += int(row["satisfaction_score"])
                    count += 1
                

            else:
                filasInvalidas += 1

                incident_id = row.get("incident_id", "UNKNOWN")
                listaErrores.append({"incident_id": incident_id, "errors": errors})
        mediaSatisfaccion = total / count if count > 0 else 0

    return {
        "valid": filasValidas,
        "invalid": filasInvalidas,
        "categories": categoryCount,
        "statuses": statusCount,
        "media_satisfaccion": mediaSatisfaccion,
        "errores": listaErrores
    }
# =========================================================
# PRESENTACIÓN DE RESULTADOS
# =========================================================

def printResults(results):

    print("\n========================================")
    print("       INCIDENT ANALYSIS REPORT")
    print("========================================\n")

    # 1. Resumen general
    print("SUMMARY")
    print("----------------------------------------")
    print(f"Valid rows:   {results['valid']}")
    print(f"Invalid rows: {results['invalid']}")

    # 2. Detalle de filas inválidas
    print("\nINVALID INCIDENTS")
    print("----------------------------------------")

    if results["errores"]:
        for incident in results["errores"]:
            print(f"\nIncident ID: {incident['incident_id']}")

            for error in incident["errors"]:
                print(f"  - {error}")
    else:
        print("No invalid incidents found.")

    # 3. Tabla de categorías
    print("\nCATEGORY BREAKDOWN")
    print("----------------------------------------")
    print("| Category | Count |")
    print("|----------|------:|")

    for category, count in results["categories"].items():
        print(f"| {category} | {count} |")

    # 4. Tabla de estados
    print("\nSTATUS BREAKDOWN")
    print("----------------------------------------")
    print("| Status | Count |")
    print("|--------|------:|")

    for status, count in results["statuses"].items():
        print(f"| {status} | {count} |")

    # 5. Media de satisfacción
    print("\nSATISFACTION")
    print("----------------------------------------")
    print(f"Average satisfaction score: {results['media_satisfaccion']:.2f}")

    print("\n========================================")

# =========================================================
# EXPORTAR A CSV
# =========================================================

def exportResults(results, filePath="results.csv"):
    """Escribe el resumen en un CSV. Devuelve False si no se pudo escribir el archivo."""

    try:
        with open(filePath, "w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)

            writer.writerow(["metric", "value"])

            # Totales
            writer.writerow(["valid_rows", results["valid"]])
            writer.writerow(["invalid_rows", results["invalid"]])

            # Categorías
            for category, count in results["categories"].items():
                writer.writerow([f"category_{category}", count])

            # Estados
            for status, count in results["statuses"].items():
                writer.writerow([f"status_{status}", count])

            # Satisfacción
            writer.writerow([
                "average_satisfaction",
                f"{results['media_satisfaccion']:.2f}"
            ])
    except OSError as error:
        # Archivo abierto en otro programa, sin permisos, ruta inexistente...
        print(f"\nNo se pudo escribir {filePath}: {error.strerror or error}", file=sys.stderr)
        return False

    print(f"\nResultados exportados correctamente a {filePath}")
    return True

# =========================================================
# EJECUCIÓN
# =========================================================
#
#   python scripts/analyze.py                      analiza csv/incidents-trackflow.csv
#   python scripts/analyze.py otro.csv             analiza otro archivo
#   python scripts/analyze.py --export             exporta a results.csv sin preguntar
#   python scripts/analyze.py --export=salida.csv  exporta a otro archivo
#
# Código de salida 1 si el CSV no se puede leer o la exportación falla.

def main():
    exportPath = None
    paths = []
    for arg in sys.argv[1:]:
        if arg == "--export":
            exportPath = "results.csv"
        elif arg.startswith("--export="):
            exportPath = arg.split("=", 1)[1] or "results.csv"
        else:
            paths.append(arg)

    filePath = paths[0] if paths else "csv/incidents-trackflow.csv"

    try:
        results = analyzeCsv(filePath)
    except FileNotFoundError:
        print(f"No se encuentra el archivo: {filePath}", file=sys.stderr)
        sys.exit(1)
    except UnicodeDecodeError:
        print(f"El archivo {filePath} no está codificado en UTF-8.", file=sys.stderr)
        sys.exit(1)
    except (OSError, csv.Error) as error:
        print(f"No se pudo leer {filePath} como CSV: {error}", file=sys.stderr)
        sys.exit(1)

    printResults(results)

    if exportPath is None:
        try:
            exportar = input("\n¿Quieres exportar los resultados a CSV? (s/n): ")
        except EOFError:
            # Sin terminal (tarea programada, CI): no hay a quién preguntar.
            exportar = "n"
        if exportar.lower() == "s":
            exportPath = "results.csv"

    if exportPath is not None and not exportResults(results, exportPath):
        sys.exit(1)


if __name__ == "__main__":
    main()
