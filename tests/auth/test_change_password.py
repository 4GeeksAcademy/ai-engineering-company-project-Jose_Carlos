"""POST /auth/change-password — change_password (ruta y servicio)."""

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from services.api import user_service
from services.api.routes.auth import change_password, reset_password
from services.api.user_models import ChangePasswordRequest, ResetPasswordRequest

NEW_PASSWORD = "brand-new-password"


def _change(user, current_password, new_password=NEW_PASSWORD):
    body = ChangePasswordRequest(current_password=current_password, new_password=new_password)
    return change_password(body, current_user=user)


def _assert_rejected(user, current_password):
    with pytest.raises(HTTPException) as error:
        _change(user, current_password)
    assert error.value.status_code == 400
    assert error.value.detail == "Current password is incorrect"


# =========================================================
# Camino feliz
# =========================================================


def test_change_password_with_the_right_current_password(user, password):
    result = _change(user, password)

    assert result == {"message": "Password updated"}
    assert user_service.authenticate(user["email"], NEW_PASSWORD) is not None
    assert user_service.authenticate(user["email"], password) is None
    stored = user_service.get_user_by_id(user["id"])["hashed_password"]
    assert stored.startswith("$2") and NEW_PASSWORD not in stored


# =========================================================
# Casos límite
# =========================================================


def test_change_password_invalidates_pending_reset_links(user, password):
    _, token = user_service.create_password_reset(user["email"])

    _change(user, password)

    with pytest.raises(HTTPException) as error:
        reset_password(ResetPasswordRequest(token=token, new_password="yet-another-password"))
    assert error.value.status_code == 400
    assert user_service.authenticate(user["email"], NEW_PASSWORD) is not None


def test_change_password_only_touches_the_calling_user(user, make_user, password):
    other = make_user()

    _change(user, password)

    assert user_service.authenticate(other["email"], password) is not None


def test_change_password_accepts_new_password_on_the_boundary(user, password):
    _change(user, password, "x" * 72)

    assert user_service.authenticate(user["email"], "x" * 72) is not None


# =========================================================
# Modos de fallo
# =========================================================


@pytest.mark.parametrize("wrong_current", ["not-my-password", "", "x" * 73])
def test_change_password_with_wrong_current_password_keeps_the_old_one(user, password, wrong_current):
    _assert_rejected(user, wrong_current)

    assert user_service.authenticate(user["email"], password) is not None


def test_change_password_for_user_deleted_mid_session_is_rejected(user, password):
    user_service.delete_user(user["id"])

    _assert_rejected(user, password)


@pytest.mark.parametrize("bad_password", ["short", "x" * 73, "abcdefg\x00hij", ""])
def test_change_password_rejects_invalid_new_password(bad_password):
    with pytest.raises(ValidationError):
        ChangePasswordRequest(current_password="s3cret-password", new_password=bad_password)


def test_change_password_request_requires_the_current_password():
    with pytest.raises(ValidationError):
        ChangePasswordRequest.model_validate({"new_password": NEW_PASSWORD})
