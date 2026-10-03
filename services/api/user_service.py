"""Capa de servicios de usuarios y perfiles.

User y Profile viven SOLO en TinyDB (mismo archivo que los proveedores). El `id` de
User es un UUID en texto: es lo que viaja en el JWT (`sub`) y lo que otros módulos
guardan como `user_uuid`.
"""

import uuid
from datetime import datetime, timedelta, timezone

from tinydb import Query

from services.api import config
from services.api.security import (
    DUMMY_HASH,
    create_password_reset_token,
    decode_password_reset_token,
    hash_password,
    verify_password,
)
from services.api.store import _lock, db
from services.api.user_models import UserRole


users_table = db.table("users")
profiles_table = db.table("profiles")
# Un registro por enlace de restablecimiento emitido: permite invalidarlo tras su uso.
password_resets_table = db.table("password_resets")

UserQuery = Query()
ProfileQuery = Query()
ResetQuery = Query()

PROFILE_FIELDS = ("name", "phone", "address")


class EmailAlreadyRegistered(Exception):
    pass


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _plain(doc) -> dict | None:
    return None if doc is None else dict(doc)


# =========================================================
# USUARIOS
# =========================================================


def create_user(
    email: str,
    password: str,
    role: UserRole = UserRole.USER,
    profile: dict | None = None,
) -> tuple[dict, dict]:
    """Crea el User (con la contraseña hasheada) y su Profile vinculado en una sola operación."""
    email = _normalize_email(email)
    # Hasheamos fuera del lock: bcrypt es lento a propósito.
    hashed_password = hash_password(password)
    profile = profile or {}

    with _lock:
        if users_table.contains(UserQuery.email == email):
            raise EmailAlreadyRegistered(email)

        user = {
            "id": str(uuid.uuid4()),
            "email": email,
            "hashed_password": hashed_password,
            "is_active": True,
            "role": UserRole(role).value,
            "created_at": datetime.now(tz=timezone.utc).isoformat(),
        }
        user_profile = {
            "id": str(uuid.uuid4()),
            "user_id": user["id"],
            **{field: profile.get(field) for field in PROFILE_FIELDS},
        }
        users_table.insert(user)
        profiles_table.insert(user_profile)
    return user, user_profile


def list_users() -> list[dict]:
    with _lock:
        return [_plain(doc) for doc in users_table.all()]


def get_user_by_id(user_id: str) -> dict | None:
    with _lock:
        return _plain(users_table.get(UserQuery.id == user_id))


def get_user_by_email(email: str) -> dict | None:
    with _lock:
        return _plain(users_table.get(UserQuery.email == _normalize_email(email)))


def update_user(user_id: str, changes: dict) -> dict | None:
    """Actualiza credenciales (email, password, role, is_active). None si no existe."""
    changes = {key: value for key, value in changes.items() if value is not None}
    if "password" in changes:
        changes["hashed_password"] = hash_password(changes.pop("password"))
    if "email" in changes:
        changes["email"] = _normalize_email(changes["email"])
    if "role" in changes:
        changes["role"] = UserRole(changes["role"]).value

    with _lock:
        if not users_table.contains(UserQuery.id == user_id):
            return None
        if "email" in changes:
            owner = users_table.get(UserQuery.email == changes["email"])
            if owner is not None and owner["id"] != user_id:
                raise EmailAlreadyRegistered(changes["email"])
        if changes:
            users_table.update(changes, UserQuery.id == user_id)
        return _plain(users_table.get(UserQuery.id == user_id))


def delete_user(user_id: str) -> dict | None:
    """Elimina el usuario y su perfil vinculado. Devuelve el usuario borrado o None."""
    with _lock:
        user = _plain(users_table.get(UserQuery.id == user_id))
        if user is not None:
            users_table.remove(UserQuery.id == user_id)
            profiles_table.remove(ProfileQuery.user_id == user_id)
            password_resets_table.remove(ResetQuery.user_id == user_id)
        return user


def authenticate(email: str, password: str) -> dict | None:
    """Devuelve el usuario si email y contraseña coinciden (y está activo); si no, None."""
    user = get_user_by_email(email)
    if user is None:
        verify_password(password, DUMMY_HASH)
        return None
    if not verify_password(password, user["hashed_password"]):
        return None
    if not user["is_active"]:
        return None
    return user


# =========================================================
# CONTRASEÑAS: RESTABLECIMIENTO Y CAMBIO
# =========================================================


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _invalidate_resets(user_id: str, used_at: str) -> None:
    """Marca como usados todos los enlaces pendientes del usuario (llamar con el lock tomado)."""
    password_resets_table.update(
        {"used_at": used_at},
        (ResetQuery.user_id == user_id) & (ResetQuery.used_at == None),  # noqa: E711
    )


def create_password_reset(email: str) -> tuple[dict, str] | None:
    """Genera un token de restablecimiento para el usuario activo con ese email.

    Devuelve (usuario, token), o None si el email no existe, el usuario está inactivo
    o ya ha pedido demasiados enlaces en la última hora.
    """
    user = get_user_by_email(email)
    if user is None or not user["is_active"]:
        return None

    now = _now()
    hour_ago = (now - timedelta(hours=1)).isoformat()
    expires_at = now + timedelta(minutes=config.PASSWORD_RESET_EXPIRE_MINUTES)
    jti = str(uuid.uuid4())

    with _lock:
        # Limpieza: los registros de hace más de una hora ya han caducado (máx. 60 min).
        password_resets_table.remove(ResetQuery.created_at < hour_ago)
        recent = password_resets_table.count(ResetQuery.user_id == user["id"])
        if recent >= config.PASSWORD_RESET_MAX_PER_HOUR:
            return None
        password_resets_table.insert(
            {
                "jti": jti,
                "user_id": user["id"],
                "created_at": now.isoformat(),
                "expires_at": expires_at.isoformat(),
                "used_at": None,
            }
        )
    return user, create_password_reset_token(user["id"], jti, expires_at)


def reset_password(token: str, new_password: str) -> bool:
    """Cambia la contraseña con un token de restablecimiento. False si el token no es
    válido, ha caducado o ya se ha usado."""
    payload = decode_password_reset_token(token)  # firma + expiración
    if payload is None:
        return False

    # Hasheamos fuera del lock: bcrypt es lento a propósito.
    hashed_password = hash_password(new_password)
    now = _now().isoformat()

    with _lock:
        record = password_resets_table.get(ResetQuery.jti == payload["jti"])
        if record is None or record["used_at"] is not None or record["user_id"] != payload["sub"]:
            return False
        user = users_table.get(UserQuery.id == payload["sub"])
        if user is None or not user["is_active"]:
            return False

        users_table.update({"hashed_password": hashed_password}, UserQuery.id == user["id"])
        # Un solo uso: este enlace y cualquier otro pendiente del usuario quedan invalidados.
        _invalidate_resets(user["id"], now)
    return True


def change_password(user_id: str, current_password: str, new_password: str) -> bool:
    """Cambia la contraseña verificando antes la actual. False si la actual no coincide."""
    user = get_user_by_id(user_id)
    if user is None or not verify_password(current_password, user["hashed_password"]):
        return False

    hashed_password = hash_password(new_password)
    with _lock:
        users_table.update({"hashed_password": hashed_password}, UserQuery.id == user_id)
        _invalidate_resets(user_id, _now().isoformat())
    return True


# =========================================================
# PERFILES
# =========================================================


def get_profile_by_user_id(user_id: str) -> dict | None:
    with _lock:
        return _plain(profiles_table.get(ProfileQuery.user_id == user_id))


def update_profile(user_id: str, changes: dict) -> dict | None:
    """Actualiza name/phone/address del perfil del usuario. None si no existe."""
    changes = {key: value for key, value in changes.items() if key in PROFILE_FIELDS}
    with _lock:
        if not profiles_table.contains(ProfileQuery.user_id == user_id):
            return None
        if changes:
            profiles_table.update(changes, ProfileQuery.user_id == user_id)
        return _plain(profiles_table.get(ProfileQuery.user_id == user_id))
