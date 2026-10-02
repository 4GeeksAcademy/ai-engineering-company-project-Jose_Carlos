from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.hash import bcrypt

from services.api import config


# Lee la cabecera `Authorization: Bearer <token>`; si falta responde 401 por sí sola.
# tokenUrl apunta al endpoint de formulario que usa el botón "Authorize" de /docs.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")


# =========================================================
# CONTRASEÑAS (bcrypt vía libpass)
# =========================================================


def hash_password(password: str) -> str:
    return bcrypt.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.verify(password, hashed_password)
    except ValueError:
        # Hash corrupto o contraseña fuera de los límites de bcrypt.
        return False


# Hash de referencia para gastar el mismo tiempo cuando el email no existe y no
# revelar por tiempos de respuesta qué emails están registrados.
DUMMY_HASH = hash_password("dummy-password-for-timing")


# =========================================================
# JWT
# =========================================================


def create_access_token(user_id: str, expires_minutes: int | None = None) -> str:
    minutes = config.ACCESS_TOKEN_EXPIRE_MINUTES if expires_minutes is None else expires_minutes
    now = datetime.now(tz=timezone.utc)
    payload = {
        "sub": user_id,  # id del usuario en TinyDB (user_uuid en otros módulos)
        "iat": now,
        "exp": now + timedelta(minutes=minutes),
    }
    return jwt.encode(payload, config.JWT_SECRET_KEY, algorithm=config.JWT_ALGORITHM)


def decode_access_token(token: str) -> str | None:
    """Devuelve el id de usuario del token, o None si es inválido, está mal formado o ha expirado."""
    try:
        payload = jwt.decode(token, config.JWT_SECRET_KEY, algorithms=[config.JWT_ALGORITHM])
    except JWTError:
        return None
    user_id = payload.get("sub")
    return user_id if isinstance(user_id, str) and user_id else None


# =========================================================
# DEPENDENCIAS
# =========================================================


def _unauthorized(detail: str = "Could not validate credentials") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    """Decodifica el JWT y devuelve el usuario autenticado; 401 si algo falla."""
    # Import diferido para evitar un ciclo (user_service importa este módulo).
    from services.api import user_service

    user_id = decode_access_token(token)
    if user_id is None:
        raise _unauthorized()

    user = user_service.get_user_by_id(user_id)
    if user is None or not user["is_active"]:
        raise _unauthorized()
    return user


def is_admin(user: dict) -> bool:
    return user["role"] == "admin"


def ensure_self_or_admin(current_user: dict, user_id: str) -> None:
    """403 si quien llama intenta acceder a datos de otro usuario sin ser admin."""
    if current_user["id"] != user_id and not is_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not allowed to access another user's resources",
        )


def require_admin(current_user: dict = Depends(get_current_user)) -> dict:
    if not is_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required",
        )
    return current_user
