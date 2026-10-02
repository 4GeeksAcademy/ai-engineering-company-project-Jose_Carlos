from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from services.api import config, user_service
from services.api.security import create_access_token, get_current_user
from services.api.user_models import LoginRequest, MeResponse, Token


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
