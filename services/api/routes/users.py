from fastapi import APIRouter, Depends, HTTPException, status

from services.api import user_service
from services.api.security import ensure_self_or_admin, get_current_user, is_admin, require_admin
from services.api.user_models import (
    UserCreate,
    UserResponse,
    UserUpdate,
    UserWithProfileResponse,
)


# El prefijo /users se añade en main.py con app.include_router(...)
router = APIRouter(tags=["users"])


def _not_found(user_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"User {user_id} not found",
    )


def _email_taken() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="Email already registered",
    )


# =========================================================
# ENDPOINTS
# =========================================================


# Pública: registro. El rol es siempre `user`; el Profile se crea en la misma operación.
@router.post("", response_model=UserWithProfileResponse, status_code=status.HTTP_201_CREATED)
def register_user(body: UserCreate):
    try:
        user, profile = user_service.create_user(
            email=body.email,
            password=body.password,
            profile=body.model_dump(include={"name", "phone", "address"}),
        )
    except user_service.EmailAlreadyRegistered:
        raise _email_taken()
    return {**user, "profile": profile}


# Listar todos los usuarios expone credenciales de otros: solo admin (403 si no).
@router.get("", response_model=list[UserResponse])
def list_users(current_user: dict = Depends(require_admin)):
    return user_service.list_users()


@router.get("/{user_id}", response_model=UserResponse)
def get_user(user_id: str, current_user: dict = Depends(get_current_user)):
    ensure_self_or_admin(current_user, user_id)
    user = user_service.get_user_by_id(user_id)
    if user is None:
        raise _not_found(user_id)
    return user


@router.put("/{user_id}", response_model=UserResponse)
def update_user(user_id: str, body: UserUpdate, current_user: dict = Depends(get_current_user)):
    ensure_self_or_admin(current_user, user_id)
    changes = body.model_dump(exclude_unset=True)

    # role e is_active solo los cambia un admin.
    if ({"role", "is_active"} & changes.keys()) and not is_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only an admin can change role or is_active",
        )

    try:
        user = user_service.update_user(user_id, changes)
    except user_service.EmailAlreadyRegistered:
        raise _email_taken()
    if user is None:
        raise _not_found(user_id)
    return user


# Devuelve 200 con el usuario tal como estaba antes de borrarlo (igual que /suppliers).
@router.delete("/{user_id}", response_model=UserResponse)
def delete_user(user_id: str, current_user: dict = Depends(get_current_user)):
    ensure_self_or_admin(current_user, user_id)
    user = user_service.delete_user(user_id)
    if user is None:
        raise _not_found(user_id)
    return user
