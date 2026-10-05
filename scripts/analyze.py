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

    print(f"\nResultados exportados correctamente a {filePath}")

# =========================================================
# EJECUCIÓN
# =========================================================
# =========================================================
# EJECUCIÓN
# =========================================================

if __name__ == "__main__":

    results = analyzeCsv("csv/incidents-trackflow.csv")

    printResults(results)

    exportar = input("\n¿Quieres exportar los resultados a CSV? (s/n): ")

    if exportar.lower() == "s":
        exportResults(results)
