"""POST /users — registro: register_user, UserCreate y user_service.create_user."""

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from services.api import security, user_service
from services.api.routes.users import register_user
from services.api.user_models import UserCreate, UserRole, UserWithProfileResponse


def _stored(user_id):
    return user_service.users_table.get(user_service.UserQuery.id == user_id)


# =========================================================
# Camino feliz
# =========================================================


def test_register_creates_active_user_with_default_role_and_linked_profile(new_email, password):
    email = new_email()

    result = register_user(UserCreate(email=email, password=password, name="Ana", phone="123", address="Madrid"))

    assert result["email"] == email
    assert result["role"] == "user"
    assert result["is_active"] is True
    assert result["profile"]["user_id"] == result["id"]
    assert {k: result["profile"][k] for k in ("name", "phone", "address")} == {
        "name": "Ana", "phone": "123", "address": "Madrid",
    }


def test_register_stores_bcrypt_hash_and_never_the_plain_password(new_email, password):
    result = register_user(UserCreate(email=new_email(), password=password))

    stored = _stored(result["id"])
    assert stored["hashed_password"].startswith("$2")
    assert password not in str(dict(stored))
    assert security.verify_password(password, stored["hashed_password"])


def test_register_response_model_does_not_expose_the_hash(new_email, password):
    result = register_user(UserCreate(email=new_email(), password=password))

    body = UserWithProfileResponse.model_validate(result).model_dump()

    assert "hashed_password" not in body and "password" not in body


def test_hash_password_salts_each_hash():
    first, second = security.hash_password("same-password"), security.hash_password("same-password")

    assert first != second
    assert security.verify_password("same-password", first)
    assert security.verify_password("same-password", second)


# =========================================================
# Casos límite
# =========================================================


def test_register_duplicate_email_in_other_case_raises_409_and_keeps_one_user(new_email, password):
    email = new_email()
    register_user(UserCreate(email=email, password=password))

    with pytest.raises(HTTPException) as error:
        register_user(UserCreate(email=email.upper(), password="another-password"))

    assert error.value.status_code == 409
    assert error.value.detail == "Email already registered"
    assert user_service.users_table.count(user_service.UserQuery.email == email) == 1


@pytest.mark.parametrize("boundary_password", ["12345678", "x" * 72, "ñ" * 36])
def test_register_accepts_passwords_on_the_boundary(new_email, boundary_password):
    result = register_user(UserCreate(email=new_email(), password=boundary_password))

    assert security.verify_password(boundary_password, _stored(result["id"])["hashed_password"])


def test_register_without_profile_data_creates_empty_profile(new_email, password):
    result = register_user(UserCreate(email=new_email(), password=password))

    assert {k: result["profile"][k] for k in ("name", "phone", "address")} == {
        "name": None, "phone": None, "address": None,
    }
    assert user_service.get_profile_by_user_id(result["id"]) == result["profile"]


def test_register_ignores_role_sent_by_client(new_email, password):
    body = UserCreate.model_validate({"email": new_email(), "password": password, "role": "admin"})

    result = register_user(body)

    assert result["role"] == UserRole.USER.value


# =========================================================
# Modos de fallo
# =========================================================


@pytest.mark.parametrize("bad_password", [
    "1234567",   # 7 caracteres
    "x" * 73,    # 73 bytes
    "ñ" * 37,    # 37 caracteres pero 74 bytes: bcrypt la truncaría
    "",
])
def test_register_rejects_passwords_out_of_bounds(bad_password):
    with pytest.raises(ValidationError):
        UserCreate(email="a@trackflow.com", password=bad_password)


def test_register_rejects_password_with_nul_byte():
    # bcrypt no admite NUL: sin esta validación el registro acababa en un 500.
    with pytest.raises(ValidationError):
        UserCreate(email="a@trackflow.com", password="abcdefg\x00hij")


@pytest.mark.parametrize("payload", [
    {"email": "not-an-email", "password": "s3cret-password"},
    {"email": "", "password": "s3cret-password"},
    {"email": "a@trackflow.com"},
    {"password": "s3cret-password"},
])
def test_register_rejects_malformed_payload(payload):
    with pytest.raises(ValidationError):
        UserCreate.model_validate(payload)


def test_register_rolls_back_user_when_profile_cannot_be_created(new_email, password, monkeypatch):
    email = new_email()

    def boom(document):
        raise RuntimeError("disco lleno")

    monkeypatch.setattr(user_service.profiles_table, "insert", boom)

    with pytest.raises(RuntimeError):
        register_user(UserCreate(email=email, password=password))

    assert user_service.get_user_by_email(email) is None


def test_verify_password_returns_false_for_wrong_password_or_corrupt_hash():
    hashed = security.hash_password("right-password")

    assert security.verify_password("wrong-password", hashed) is False
    assert security.verify_password("right-password", "not-a-bcrypt-hash") is False
