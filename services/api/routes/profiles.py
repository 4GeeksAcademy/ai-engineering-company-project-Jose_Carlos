from fastapi import APIRouter, Depends, HTTPException, status

from services.api import user_service
from services.api.security import ensure_self_or_admin, get_current_user
from services.api.user_models import ProfileResponse, ProfileUpdate


# El prefijo /profiles se añade en main.py con app.include_router(...)
router = APIRouter(tags=["profiles"])


def _not_found(user_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Profile for user {user_id} not found",
    )


def _get_or_404(user_id: str) -> dict:
    profile = user_service.get_profile_by_user_id(user_id)
    if profile is None:
        raise _not_found(user_id)
    return profile


def _update_or_404(user_id: str, body: ProfileUpdate) -> dict:
    # exclude_unset: solo cambiamos los campos enviados (null borra el valor).
    profile = user_service.update_profile(user_id, body.model_dump(exclude_unset=True))
    if profile is None:
        raise _not_found(user_id)
    return profile


# =========================================================
# ENDPOINTS
# =========================================================

# /me se declara antes que /{user_id} para que no lo capture la ruta con parámetro.


@router.get("/me", response_model=ProfileResponse)
def get_my_profile(current_user: dict = Depends(get_current_user)):
    return _get_or_404(current_user["id"])


@router.put("/me", response_model=ProfileResponse)
def update_my_profile(body: ProfileUpdate, current_user: dict = Depends(get_current_user)):
    return _update_or_404(current_user["id"], body)


# Acceso al perfil de un usuario concreto: solo su dueño o un admin (403 si no).
@router.get("/{user_id}", response_model=ProfileResponse)
def get_profile(user_id: str, current_user: dict = Depends(get_current_user)):
    ensure_self_or_admin(current_user, user_id)
    return _get_or_404(user_id)


@router.put("/{user_id}", response_model=ProfileResponse)
def update_profile(user_id: str, body: ProfileUpdate, current_user: dict = Depends(get_current_user)):
    ensure_self_or_admin(current_user, user_id)
    return _update_or_404(user_id, body)
