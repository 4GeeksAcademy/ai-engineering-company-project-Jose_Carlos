from fastapi import Depends, FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from scripts.analyze import analyzeCsv
from services.api.errors import register_error_handlers
from services.api.routes.auth import router as auth_router
from services.api.routes.incidents import router as incidents_router
from services.api.routes.profiles import router as profiles_router
from services.api.routes.suppliers import router as suppliers_router
from services.api.routes.users import router as users_router
from services.api.security import get_current_user
import tempfile
import csv, io
import os
from pathlib import Path
from fastapi.responses import Response


app = FastAPI()

# Respuestas de error comunes: 500 genérico en JSON y errores de validación.
register_error_handlers(app)

codespace_name = os.getenv("CODESPACE_NAME")
codespace_domain = os.getenv("GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN")
# 5500: backoffice servido aparte (Live Server). 3000: app Next.js (talent-pipeline-tracker).
default_cors_origins = [
    "http://localhost:5500",
    "http://127.0.0.1:5500",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

if codespace_name and codespace_domain:
    default_cors_origins += [
        f"https://{codespace_name}-5500.{codespace_domain}",
        f"https://{codespace_name}-3000.{codespace_domain}",
    ]

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
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/auth")
app.include_router(users_router, prefix="/users")
app.include_router(profiles_router, prefix="/profiles")
# Todas las rutas de /suppliers requieren un JWT válido (la dependencia está en el router).
app.include_router(suppliers_router, prefix="/suppliers")
# Gestor de incidencias (CONTEXT-8): CRUD, resumen y capa semántica. También con JWT.
app.include_router(incidents_router, prefix="/api/incidents")

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


@app.post("/analyze", dependencies=[Depends(get_current_user)])
async def analyze_incidents(file: UploadFile = File(...)):
    contents = await file.read()
    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
        tmp.write(contents)
        tmp_path = tmp.name

    try:
        results = analyzeCsv(tmp_path)
    except (UnicodeDecodeError, csv.Error):
        # El archivo no es un CSV legible: es un problema de la petición, no del servidor.
        raise HTTPException(
            status_code=400,
            detail="El archivo no es un CSV válido codificado en UTF-8.",
        )
    finally:
        # La copia temporal contiene datos de clientes: se borra siempre, también si falla.
        os.unlink(tmp_path)

    global last_analysis
    last_analysis = results
    return results

@app.get("/api/incidents/results/export", dependencies=[Depends(get_current_user)])
def export_results():

    if last_analysis is None:
        raise HTTPException(status_code=404, detail="No existe ningún análisis")

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