"""Reglas de validación de una fila del CSV de incidencias (proyecto incidents-file-analyzer).

Lógica compartida: la usan el analizador (scripts/analyze.py, y a través de él POST /analyze)
y el seed del gestor (scripts/seed_incidents.py).
"""

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
