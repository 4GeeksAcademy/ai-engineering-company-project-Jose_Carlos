import csv 

requiredFields = [
    'incident_id',
    'date',
    'country',
    'customer_type',
    'tracking_number',
    'carrier',
    'category',
    'description',
    'status',
    'customer_email'
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




with open('csv/incidents-trackflow.csv', newline='') as file:
    reader = csv.DictReader(file)
    for row in reader:
        errors = []                                               # Creamos una lista donde recogemos todos los errores de campos que puedan existir
        # 1. Comprobar campos obligatorios
        for field in requiredFields:
            if not row.get(field):
                errors.append(f"Missing required field: {field}")

        # 2. Comprobar country
        if row.get("country") and row["country"] not in validCountries:
            errors.append("Invalid country")

        # 3. Comprobar tracking_number
        if row.get("tracking_number") and len(row["tracking_number"]) < 8:
            errors.append("Invalid tracking number")

        # 4. Comprobar carrier según el país
        country = row.get("country")
        carrier = row.get("carrier")

        if country in validCarriers and carrier:
            if carrier not in validCarriers[country]:
                errors.append("Invalid carrier for country")

        # 5. Comprobar category
        if row.get("category") and row["category"] not in validCategories:
            errors.append("Invalid category")

        # 6. Comprobar description
        if row.get("description") and len(row["description"]) < 5:
            errors.append("Invalid description")

        # 7. Comprobar status
        if row.get("status") and row["status"] not in validStatuses:
            errors.append("Invalid status")

        # 8. Comprobar email
        email = row.get("customer_email")

        if email and "@" not in email:
            errors.append("Invalid customer email")
            
        # 9. Comprobar satisfaction_score
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

        # Resultado de esta fila
        if errors:
            incident_id = row.get("incident_id", "UNKNOWN")
            print(f"Incident {incident_id} - Errors: {errors}")
