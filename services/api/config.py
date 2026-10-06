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


def _integer(name: str, default: int) -> int:
    value = os.getenv(name, "").strip()
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        raise RuntimeError(
            f"La variable de entorno {name} debe ser un número entero y vale '{value}'."
        ) from None


# Clave con la que se firman los JWT. Nunca se hardcodea: viene siempre del entorno/.env.
JWT_SECRET_KEY = _required("JWT_SECRET_KEY")

# Algoritmo de firma (HMAC con SHA-256 por defecto).
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")

# Ventana de validez del token de acceso, en minutos.
ACCESS_TOKEN_EXPIRE_MINUTES = _integer("ACCESS_TOKEN_EXPIRE_MINUTES", 30)

# ---------------------------------------------------------
# Restablecimiento de contraseña y correo transaccional (Resend)
# ---------------------------------------------------------

# Validez del enlace de restablecimiento, en minutos (entre 15 y 60).
PASSWORD_RESET_EXPIRE_MINUTES = min(60, max(15, _integer("PASSWORD_RESET_EXPIRE_MINUTES", 30)))

# Máximo de enlaces de restablecimiento que se envían a un mismo usuario por hora.
PASSWORD_RESET_MAX_PER_HOUR = _integer("PASSWORD_RESET_MAX_PER_HOUR", 5)

# API key de Resend. Si está vacía no se envía ningún correo.
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "").strip()

# Solo desarrollo: sin API key, escribe el enlace de restablecimiento en el log del servidor
# para poder probar el flujo. Quien lea ese log puede cambiar la contraseña de la cuenta,
# así que está desactivado salvo que se pida expresamente.
PASSWORD_RESET_LOG_LINK = os.getenv("PASSWORD_RESET_LOG_LINK", "").strip().lower() in ("1", "true", "yes")

# Remitente. `onboarding@resend.dev` funciona sin dominio propio, pero Resend solo
# entrega a la dirección con la que creaste la cuenta hasta que verifiques un dominio.
EMAIL_FROM = os.getenv("EMAIL_FROM", "TrackFlow <onboarding@resend.dev>")

# URL pública del frontend Next.js: base del enlace /reset-password?token=...
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000").rstrip("/")
