import os
from pathlib import Path

from dotenv import load_dotenv


# Cargamos el .env de la raíz del repo (si existe). Las variables ya definidas en el
# entorno tienen prioridad: así los tests y los despliegues pueden sobrescribirlas.
load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(
            f"Falta la variable de entorno {name}. Copia .env.example a .env y rellénala."
        )
    return value


# Clave con la que se firman los JWT. Nunca se hardcodea: viene siempre del entorno/.env.
JWT_SECRET_KEY = _required("JWT_SECRET_KEY")

# Algoritmo de firma (HMAC con SHA-256 por defecto).
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")

# Ventana de validez del token de acceso, en minutos.
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
