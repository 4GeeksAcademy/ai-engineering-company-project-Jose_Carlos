"""POST /auth/token — login por formulario OAuth2 y JWT de acceso."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from jose import jwt

from services.api import config, security
from services.api.routes.auth import login, login_form
from services.api.user_models import LoginRequest


def _form(username, password):
    return OAuth2PasswordRequestForm(username=username, password=password)


def _claims(token):
    return jwt.decode(token, config.JWT_SECRET_KEY, algorithms=[config.JWT_ALGORITHM])


def _signed(payload, key=None):
    return jwt.encode(payload, key or config.JWT_SECRET_KEY, algorithm=config.JWT_ALGORITHM)


def _in_five_minutes():
    return datetime.now(tz=timezone.utc) + timedelta(minutes=5)


# =========================================================
# Camino feliz
# =========================================================


def test_token_form_login_uses_username_as_email(user, password):
    result = login_form(_form(user["email"], password))

    assert result["token_type"] == "bearer"
    assert result["expires_in"] == config.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    assert security.decode_access_token(result["access_token"]) == user["id"]


def test_access_token_claims_carry_type_and_configured_expiry(user):
    claims = _claims(security.create_access_token(user["id"]))

    assert claims["sub"] == user["id"]
    assert claims["type"] == security.ACCESS_TOKEN_TYPE
    assert claims["exp"] - claims["iat"] == config.ACCESS_TOKEN_EXPIRE_MINUTES * 60


def test_form_and_json_login_issue_equivalent_tokens(user, password):
    from_form = _claims(login_form(_form(user["email"], password))["access_token"])
    from_json = _claims(login(LoginRequest(email=user["email"], password=password))["access_token"])

    assert (from_form["sub"], from_form["type"]) == (from_json["sub"], from_json["type"])


# =========================================================
# Casos límite
# =========================================================


def test_access_token_honours_custom_expiry(user):
    claims = _claims(security.create_access_token(user["id"], expires_minutes=1))

    assert claims["exp"] - claims["iat"] == 60


def test_token_form_login_matches_username_regardless_of_case(user, password):
    result = login_form(_form(user["email"].upper(), password))

    assert security.decode_access_token(result["access_token"]) == user["id"]


# =========================================================
# Modos de fallo
# =========================================================


@pytest.mark.parametrize("username_kind,form_password", [
    ("known", "wrong-password"),
    ("unknown", "s3cret-password"),
    ("empty", "s3cret-password"),
])
def test_token_form_login_with_bad_credentials_raises_401(user, new_email, username_kind, form_password):
    username = {"known": user["email"], "unknown": new_email("ghost"), "empty": ""}[username_kind]

    with pytest.raises(HTTPException) as error:
        login_form(_form(username, form_password))

    assert error.value.status_code == 401
    assert error.value.headers == {"WWW-Authenticate": "Bearer"}


def _invalid_access_tokens(user_id):
    exp = _in_five_minutes()
    return {
        "expired": security.create_access_token(user_id, expires_minutes=-1),
        "garbage": "abc",
        "malformed": "not.a.jwt",
        "empty": "",
        "wrong_signature": _signed({"sub": user_id, "type": "access", "exp": exp}, key="another-secret"),
        "missing_sub": _signed({"type": "access", "exp": exp}),
        "empty_sub": _signed({"sub": "", "type": "access", "exp": exp}),
        "non_string_sub": _signed({"sub": 42, "type": "access", "exp": exp}),
        "missing_type": _signed({"sub": user_id, "exp": exp}),
        # Un enlace de restablecimiento no sirve como sesión.
        "password_reset_type": security.create_password_reset_token(user_id, str(uuid.uuid4()), exp),
    }


@pytest.mark.parametrize("kind", [
    "expired", "garbage", "malformed", "empty", "wrong_signature", "missing_sub",
    "empty_sub", "non_string_sub", "missing_type", "password_reset_type",
])
def test_decode_access_token_returns_none_for_invalid_tokens(user, kind):
    assert security.decode_access_token(_invalid_access_tokens(user["id"])[kind]) is None
