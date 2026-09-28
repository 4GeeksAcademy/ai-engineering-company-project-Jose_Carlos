from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from scripts.analyze import analyzeCsv
import tempfile
import csv, io
import os
from pathlib import Path
from fastapi.responses import Response


app = FastAPI()

codespace_name = os.getenv("CODESPACE_NAME")
codespace_domain = os.getenv("GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN")
default_cors_origins = [
    "http://localhost:5500",
    "http://127.0.0.1:5500",
]

if codespace_name and codespace_domain:
    default_cors_origins.append(
        f"https://{codespace_name}-5500.{codespace_domain}"
    )

cors_origins = [
    origin.strip()
    for origin in os.getenv(
        "BACKOFFICE_CORS_ORIGINS",
        ",".join(default_cors_origins),
    ).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

last_analysis = None

@app.get("/")
def read_root():
    return {"message": "Bienvenid@ a la API de análisis de incidentes"}

# =========================================================
# ENDPOINTS
# =========================================================


# =========================================================
# Este fragmento recibe el archivo subido por la API y lee su contenido de forma asíncrona. 
# Como analyzeCSV necesita una ruta a un archivo físico y no puede trabajar directamente con el objeto subido, c
# reamos un archivo temporal en disco y escribimos en él los bytes leídos. Después obtenemos la ruta de ese archivo temporal 
# y se la pasamos a analyzeCSV para que haga el análisis y nos devuelva los resultados. 
# En el fondo es un pequeño puente entre cómo FastAPI entrega archivos y cómo tu analizador sabe trabajar.
# =========================================================


@app.post("/analyze")
async def analyze_incidents(file: UploadFile = File(...)):
    contents = await file.read()
    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:    
        tmp.write(contents)
        tmp_path = tmp.name

    results = analyzeCsv(tmp_path)
    global last_analysis
    last_analysis = results
    return results

@app.get("/api/incidents/results/export")
def export_results():

    if last_analysis is None:
        return {"message": "No existe ningún análisis"}

    # Creamos un archivo de texto en memoria
    salida = io.StringIO()
    writer = csv.writer(salida)

    # Cabecera
    writer.writerow(["metric", "value"])

    # Totales
    writer.writerow(["valid_rows", last_analysis["valid"]])
    writer.writerow(["invalid_rows", last_analysis["invalid"]])

    # Categorías
    for category, count in last_analysis["categories"].items():
        writer.writerow([f"category_{category}", count])

    # Estados
    for status, count in last_analysis["statuses"].items():
        writer.writerow([f"status_{status}", count])

    # Satisfacción
    writer.writerow([
        "average_satisfaction",
        f"{last_analysis['media_satisfaccion']:.2f}"
    ])

    # Extraemos el contenido CSV que hemos construido en memoria
    csv_content = salida.getvalue()

    # Devolvemos una respuesta HTTP que el navegador interpreta como archivo CSV
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=results.csv"
        }
    )


backoffice_path = Path(__file__).resolve().parents[2] / "uis" / "backoffice"
app.mount(
    "/backoffice",
    StaticFiles(directory=backoffice_path, html=True),
    name="backoffice",
)