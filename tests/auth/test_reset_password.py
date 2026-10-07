"""POST /auth/reset-password — reset_password (ruta y servicio)."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from services.api import security, user_service
from services.api.routes.auth import reset_password
from services.api.user_models import ResetPasswordRequest

NEW_PASSWORD = "brand-new-password"


def _issue(user):
    _, token = user_service.create_password_reset(user["email"])
    return token


def _reset(token, new_password=NEW_PASSWORD):
    return reset_password(ResetPasswordRequest(token=token, new_password=new_password))


def _assert_rejected(token):
    with pytest.raises(HTTPException) as error:
        _reset(token)
    assert error.value.status_code == 400
    assert error.value.detail == "Invalid, expired or already used reset token"


# =========================================================
# Camino feliz
# =========================================================


def test_reset_password_replaces_the_password(user, password):
    result = _reset(_issue(user))

    assert result == {"message": "Password updated"}
    assert user_service.authenticate(user["email"], NEW_PASSWORD) is not None
    assert user_service.authenticate(user["email"], password) is None
    stored = user_service.get_user_by_id(user["id"])["hashed_password"]
    assert stored.startswith("$2") and NEW_PASSWORD not in stored


# =========================================================
# Casos límite
# =========================================================


def test_reset_token_is_single_use(user):
    token = _issue(user)
    _reset(token)

    with pytest.raises(HTTPException) as error:
        _reset(token, "yet-another-password")

    assert error.value.status_code == 400
    assert user_service.authenticate(user["email"], NEW_PASSWORD) is not None


def test_using_one_link_invalidates_the_other_pending_links(user):
    first, second = _issue(user), _issue(user)

    _reset(second)

    _assert_rejected(first)


def test_reset_password_accepts_new_password_on_the_boundary(user):
    _reset(_issue(user), "12345678")

    assert user_service.authenticate(user["email"], "12345678") is not None


def test_rejected_new_password_does_not_consume_the_link(user):
    token = _issue(user)
    with pytest.raises(ValidationError):
        ResetPasswordRequest(token=token, new_password="short")

    assert _reset(token) == {"message": "Password updated"}


# =========================================================
# Modos de fallo
# =========================================================


def test_expired_reset_token_is_rejected(user, password, monkeypatch):
    # Emitido hace dos horas: bien firmado y registrado, pero ya caducado.
    real_now = user_service._now
    monkeypatch.setattr(user_service, "_now", lambda: real_now() - timedelta(hours=2))
    token = _issue(user)
    monkeypatch.setattr(user_service, "_now", real_now)

    _assert_rejected(token)
    assert user_service.authenticate(user["email"], password) is not None


def _invalid_reset_tokens(user, valid):
    future = datetime.now(tz=timezone.utc) + timedelta(minutes=10)
    return {
        "garbage": "not-a-token",
        "empty": "",
        "tampered": valid[:-4] + ("AAAA" if not valid.endswith("AAAA") else "BBBB"),
        # Firmado y vigente, pero nunca emitido por /forgot-password.
        "unregistered_jti": security.create_password_reset_token(user["id"], str(uuid.uuid4()), future),
        # Un token de sesión no sirve para restablecer la contraseña.
        "access_token": security.create_access_token(user["id"]),
    }


@pytest.mark.parametrize("kind", ["garbage", "empty", "tampered", "unregistered_jti", "access_token"])
def test_invalid_reset_tokens_are_rejected_and_keep_the_password(user, password, kind):
    token = _invalid_reset_tokens(user, _issue(user))[kind]

    _assert_rejected(token)
    assert user_service.authenticate(user["email"], password) is not None


def test_reset_token_bound_to_another_users_link_is_rejected(user, make_user, password):
    # Token firmado para `user` que reutiliza el jti del enlace de otra persona.
    other = make_user()
    other_jti = security.decode_password_reset_token(_issue(other))["jti"]
    future = datetime.now(tz=timezone.utc) + timedelta(minutes=10)

    _assert_rejected(security.create_password_reset_token(user["id"], other_jti, future))
    assert user_service.authenticate(other["email"], password) is not None


def test_reset_is_rejected_when_user_was_deactivated_after_the_link_was_sent(user):
    token = _issue(user)
    user_service.update_user(user["id"], {"is_active": False})

    _assert_rejected(token)


def test_reset_is_rejected_when_user_was_deleted_after_the_link_was_sent(user):
    token = _issue(user)
    user_service.delete_user(user["id"])

    _assert_rejected(token)


@pytest.mark.parametrize("bad_password", ["short", "x" * 73, "abcdefg\x00hij", ""])
def test_reset_password_rejects_invalid_new_password(bad_password):
    with pytest.raises(ValidationError):
        ResetPasswordRequest(token="any-token", new_password=bad_password)


def test_reset_password_request_requires_a_token():
    with pytest.raises(ValidationError):
        ResetPasswordRequest.model_validate({"new_password": NEW_PASSWORD})
