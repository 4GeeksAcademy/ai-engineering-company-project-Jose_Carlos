"""GET /auth/me — read_me y la dependencia get_current_user."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from services.api import security, user_service
from services.api.routes.auth import read_me
from services.api.user_models import MeResponse


# =========================================================
# Camino feliz
# =========================================================


def test_get_current_user_resolves_a_valid_token_to_its_user(user):
    assert security.get_current_user(security.create_access_token(user["id"])) == user


def test_me_returns_the_user_with_their_profile(make_user):
    user = make_user(profile={"name": "Alice", "phone": "+34 600 000 001"})

    result = read_me(current_user=user)

    assert result["id"] == user["id"]
    assert result["email"] == user["email"]
    assert result["role"] == "user"
    assert result["profile"]["user_id"] == user["id"]
    assert result["profile"]["name"] == "Alice"
    assert result["profile"]["phone"] == "+34 600 000 001"


def test_me_response_model_does_not_expose_the_hash(user):
    body = MeResponse.model_validate(read_me(current_user=user)).model_dump()

    assert set(body) == {"id", "email", "role", "profile"}


# =========================================================
# Casos límite
# =========================================================


def test_me_for_user_without_profile_returns_profile_none(user):
    user_service.profiles_table.remove(user_service.ProfileQuery.user_id == user["id"])

    result = read_me(current_user=user)

    assert result["profile"] is None
    assert MeResponse.model_validate(result).profile is None


# =========================================================
# Modos de fallo
# =========================================================


def _assert_unauthorized(token):
    with pytest.raises(HTTPException) as error:
        security.get_current_user(token)
    assert error.value.status_code == 401
    assert error.value.detail == "Could not validate credentials"
    assert error.value.headers == {"WWW-Authenticate": "Bearer"}


def test_get_current_user_rejects_expired_token(user):
    _assert_unauthorized(security.create_access_token(user["id"], expires_minutes=-1))


@pytest.mark.parametrize("token", ["", "abc", "not.a.jwt"])
def test_get_current_user_rejects_unreadable_token(token):
    _assert_unauthorized(token)


def test_get_current_user_rejects_password_reset_token(user):
    expires_at = datetime.now(tz=timezone.utc) + timedelta(minutes=5)
    _assert_unauthorized(security.create_password_reset_token(user["id"], str(uuid.uuid4()), expires_at))


def test_get_current_user_rejects_token_of_unknown_user():
    _assert_unauthorized(security.create_access_token(str(uuid.uuid4())))


def test_get_current_user_rejects_token_of_deleted_user(user):
    token = security.create_access_token(user["id"])
    user_service.delete_user(user["id"])

    _assert_unauthorized(token)


def test_get_current_user_rejects_token_of_inactive_user(user):
    token = security.create_access_token(user["id"])
    user_service.update_user(user["id"], {"is_active": False})

    _assert_unauthorized(token)
