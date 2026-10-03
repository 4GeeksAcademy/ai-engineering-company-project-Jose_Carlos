from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from services.api import config, email_service, user_service
from services.api.security import create_access_token, get_current_user
from services.api.user_models import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    MeResponse,
    MessageResponse,
    ResetPasswordRequest,
    Token,
)


# El prefijo /auth se añade en main.py con app.include_router(...)
router = APIRouter(tags=["auth"])


def _issue_token(email: str, password: str) -> dict:
    user = user_service.authenticate(email, password)
    if user is None:
        # Mismo mensaje para email inexistente y contraseña incorrecta.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return {
        "access_token": create_access_token(user["id"]),
        "token_type": "bearer",
        "expires_in": config.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    }


# =========================================================
# ENDPOINTS
# =========================================================


# Login con JSON {email, password}: lo que usan los clientes de la API.
@router.post("/login", response_model=Token)
def login(body: LoginRequest):
    return _issue_token(body.email, body.password)


# Mismo login en formato formulario OAuth2 (campo `username` = email). Es el tokenUrl
# de OAuth2PasswordBearer, así funciona el botón "Authorize" de /docs.
@router.post("/token", response_model=Token)
def login_form(form: OAuth2PasswordRequestForm = Depends()):
    return _issue_token(form.username, form.password)


@router.get("/me", response_model=MeResponse)
def read_me(current_user: dict = Depends(get_current_user)):
    profile = user_service.get_profile_by_user_id(current_user["id"])
    return {**current_user, "profile": profile}


# =========================================================
# CONTRASEÑAS: RESTABLECIMIENTO Y CAMBIO
# =========================================================


def _send_reset_link(email: str) -> None:
    result = user_service.create_password_reset(email)
    if result is not None:
        user, token = result
        email_service.send_password_reset_email(user["email"], token)


# Siempre 200 con el mismo mensaje, exista o no el email. La búsqueda, el token y el
# envío van en segundo plano para que tampoco el tiempo de respuesta lo revele.
@router.post("/forgot-password", response_model=MessageResponse)
def forgot_password(body: ForgotPasswordRequest, background_tasks: BackgroundTasks):
    background_tasks.add_task(_send_reset_link, body.email)
    return {"message": "If that address is registered, you will receive a reset link shortly."}


@router.post("/reset-password", response_model=MessageResponse)
def reset_password(body: ResetPasswordRequest):
    if not user_service.reset_password(body.token, body.new_password):
        # Mismo error para token inválido, caducado o ya utilizado.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid, expired or already used reset token",
        )
    return {"message": "Password updated"}


@router.post("/change-password", response_model=MessageResponse)
def change_password(body: ChangePasswordRequest, current_user: dict = Depends(get_current_user)):
    if not user_service.change_password(current_user["id"], body.current_password, body.new_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )
    return {"message": "Password updated"}
