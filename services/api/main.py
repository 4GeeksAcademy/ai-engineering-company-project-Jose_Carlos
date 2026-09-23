from fastapi import FastAPI, UploadFile, File
from scripts.analyze import analyzeCsv
import tempfile


app = FastAPI()



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
    return results

