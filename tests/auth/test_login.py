"""POST /auth/login — login y user_service.authenticate."""

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from services.api import config, security, user_service
from services.api.routes.auth import login
from services.api.user_models import LoginRequest


def _assert_bad_credentials(error):
    assert error.value.status_code == 401
    assert error.value.detail == "Incorrect email or password"
    assert error.value.headers == {"WWW-Authenticate": "Bearer"}


# =========================================================
# Camino feliz
# =========================================================


def test_login_returns_bearer_token_for_the_user(user, password):
    result = login(LoginRequest(email=user["email"], password=password))

    assert result["token_type"] == "bearer"
    assert result["expires_in"] == config.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    assert security.decode_access_token(result["access_token"]) == user["id"]


def test_authenticate_returns_the_stored_user(user, password):
    assert user_service.authenticate(user["email"], password) == user


# =========================================================
# Casos límite
# =========================================================


def test_login_matches_email_regardless_of_case(user, password):
    result = login(LoginRequest(email=user["email"].upper(), password=password))

    assert security.decode_access_token(result["access_token"]) == user["id"]


def test_authenticate_ignores_surrounding_whitespace_in_email(user, password):
    assert user_service.authenticate(f"  {user['email']} ", password) == user


@pytest.mark.parametrize("odd_password", ["", "x" * 73, "abc\x00def"])
def test_login_with_password_bcrypt_cannot_check_is_401_not_a_crash(user, odd_password):
    with pytest.raises(HTTPException) as error:
        login(LoginRequest(email=user["email"], password=odd_password))

    _assert_bad_credentials(error)


# =========================================================
# Modos de fallo
# =========================================================


def test_login_wrong_password_and_unknown_email_give_the_same_401(user, password, new_email):
    with pytest.raises(HTTPException) as wrong_password:
        login(LoginRequest(email=user["email"], password="wrong-password"))
    with pytest.raises(HTTPException) as unknown_email:
        login(LoginRequest(email=new_email("ghost"), password=password))

    _assert_bad_credentials(wrong_password)
    _assert_bad_credentials(unknown_email)


def test_login_inactive_user_is_rejected_even_with_the_right_password(user, password):
    user_service.update_user(user["id"], {"is_active": False})

    with pytest.raises(HTTPException) as error:
        login(LoginRequest(email=user["email"], password=password))

    _assert_bad_credentials(error)


def test_authenticate_unknown_email_still_spends_a_bcrypt_check(new_email, password, monkeypatch):
    # Sin esta verificación de relleno, el tiempo de respuesta revelaría qué emails existen.
    checked = []

    def fake_verify(plain, hashed):
        checked.append(hashed)
        return False

    monkeypatch.setattr(user_service, "verify_password", fake_verify)

    assert user_service.authenticate(new_email("ghost"), password) is None
    assert checked == [security.DUMMY_HASH]


@pytest.mark.parametrize("payload", [
    {"email": "not-an-email", "password": "s3cret-password"},
    {"email": "a@trackflow.com"},
    {"password": "s3cret-password"},
])
def test_login_rejects_malformed_request(payload):
    with pytest.raises(ValidationError):
        LoginRequest.model_validate(payload)
