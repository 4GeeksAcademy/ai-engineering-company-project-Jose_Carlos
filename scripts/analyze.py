import csv


# =========================================================
# REGLAS DE VALIDACIÓN
# =========================================================

requiredFields = [
    "incident_id",
    "date",
    "country",
    "customer_type",
    "tracking_number",
    "carrier",
    "category",
    "description",
    "status",
    "customer_email"
]

validCountries = ["US", "ES"]

validCarriers = {
    "US": ["UPS", "FEDEX", "DHL_US"],
    "ES": ["MRW", "SEUR", "DHL_ES", "LOCAL_ES"]
}

validCategories = [
    "LOST_PARCEL",
    "DELAYED_DELIVERY",
    "WRONG_ADDRESS",
    "RETURN_REQUEST",
    "DAMAGE"
]

validStatuses = ["OPEN", "CLOSED", "DISCARDED"]


# =========================================================
# VALIDACIÓN DE UNA INCIDENCIA
# =========================================================

def validateIncident(row):
    errors = []

    # Campos obligatorios
    for field in requiredFields:
        if not row.get(field):
            errors.append(f"Missing required field: {field}")

    # Country
    if row.get("country") and row["country"] not in validCountries:
        errors.append("Invalid country")

    # Tracking number
    if row.get("tracking_number") and len(row["tracking_number"]) < 8:
        errors.append("Invalid tracking number")

    # Carrier según país
    country = row.get("country")
    carrier = row.get("carrier")

    if country in validCarriers and carrier:
        if carrier not in validCarriers[country]:
            errors.append("Invalid carrier for country")

    # Category
    if row.get("category") and row["category"] not in validCategories:
        errors.append("Invalid category")

    # Description
    if row.get("description") and len(row["description"]) < 5:
        errors.append("Invalid description")

    # Status
    if row.get("status") and row["status"] not in validStatuses:
        errors.append("Invalid status")

    # Email
    email = row.get("customer_email")

    if email and "@" not in email:
        errors.append("Invalid customer email")

    # Satisfaction score
    score = row.get("satisfaction_score")

    if row.get("status") == "CLOSED" and not score:
        errors.append("Closed incident without satisfaction score")

    if score:
        try:
            scoreNumber = int(score)

            if scoreNumber < 1 or scoreNumber > 5:
                errors.append("Satisfaction score out of range")

        except ValueError:
            errors.append("Invalid satisfaction score")

    return errors


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