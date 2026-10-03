from datetime import datetime
from enum import Enum

from pydantic import BaseModel, EmailStr, Field, field_validator


# --------------------------------------------------
# ENUMS
# --------------------------------------------------

class UserRole(str, Enum):
    ADMIN = "admin"
    MANAGER = "manager"
    USER = "user"


# --------------------------------------------------
# VALIDACIONES COMUNES
# --------------------------------------------------

# bcrypt solo usa los primeros 72 bytes de la contraseña: rechazamos las más largas
# en vez de truncarlas en silencio.
def _check_password(value: str) -> str:
    if len(value.encode("utf-8")) > 72:
        raise ValueError("Password must be at most 72 bytes")
    return value


# --------------------------------------------------
# PERFIL (nombre visible y datos de contacto)
# --------------------------------------------------

class ProfileData(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    phone: str | None = Field(default=None, max_length=40)
    address: str | None = Field(default=None, max_length=255)


class ProfileUpdate(ProfileData):
    pass


class ProfileResponse(ProfileData):
    id: str
    user_id: str


# --------------------------------------------------
# USUARIO (solo credenciales)
# --------------------------------------------------

# No declara role: los registros públicos son siempre `user` (si el cliente envía
# role, Pydantic lo ignora). name/phone/address son el perfil inicial opcional.
class UserCreate(ProfileData):
    email: EmailStr
    password: str = Field(..., min_length=8)

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        return _check_password(value)


class UserUpdate(BaseModel):
    email: EmailStr | None = None
    password: str | None = Field(default=None, min_length=8)
    # Solo un admin puede cambiar role o is_active (si no, 403).
    role: UserRole | None = None
    is_active: bool | None = None

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str | None) -> str | None:
        return None if value is None else _check_password(value)


# Nunca incluye hashed_password.
class UserResponse(BaseModel):
    id: str
    email: EmailStr
    is_active: bool
    role: UserRole
    created_at: datetime


class UserWithProfileResponse(UserResponse):
    profile: ProfileResponse | None


# --------------------------------------------------
# AUTH
# --------------------------------------------------

class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # segundos


class MeResponse(BaseModel):
    id: str
    email: EmailStr
    role: UserRole
    profile: ProfileResponse | None


# --------------------------------------------------
# CONTRASEÑAS: RESTABLECIMIENTO Y CAMBIO
# --------------------------------------------------

class _NewPassword(BaseModel):
    new_password: str = Field(..., min_length=8)

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, value: str) -> str:
        return _check_password(value)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(_NewPassword):
    token: str


class ChangePasswordRequest(_NewPassword):
    current_password: str


class MessageResponse(BaseModel):
    message: str
