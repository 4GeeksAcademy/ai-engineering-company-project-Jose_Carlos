"""Tests de AUTH-03: restablecimiento y cambio de contraseña."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import resend

from services.api import config, email_service, security, user_service
from services.api.security import create_access_token, create_password_reset_token

PASSWORD = "s3cret-password"
NEW_PASSWORD = "brand-new-password"
INVALID_TOKEN = {"detail": "Invalid, expired or already used reset token"}


def _email(prefix="pw"):
    return f"{prefix}-{uuid.uuid4().hex[:8]}@trackflow.com"


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


def login(client, email, password):
    return client.post("/auth/login", json={"email": email, "password": password})


@pytest.fixture
def user(anon_client):
    email = _email()
    response = anon_client.post("/users", json={"email": email, "password": PASSWORD})
    assert response.status_code == 201, response.text
    token = login(anon_client, email, PASSWORD).json()["access_token"]
    return {**response.json(), "headers": _bearer(token)}


def forgot(client, email):
    return client.post("/auth/forgot-password", json={"email": email})


def reset(client, token, new_password=NEW_PASSWORD):
    return client.post("/auth/reset-password", json={"token": token, "new_password": new_password})


def request_reset_token(client, outbox, email):
    assert forgot(client, email).status_code == 200
    return outbox[-1][1]


# =========================================================
# POST /auth/forgot-password
# =========================================================


def test_forgot_password_sends_reset_link_to_registered_email(anon_client, user, outbox):
    response = forgot(anon_client, user["email"])

    assert response.status_code == 200
    assert len(outbox) == 1
    to, token = outbox[0]
    assert to == user["email"]
    payload = security.decode_password_reset_token(token)
    assert payload["sub"] == user["id"]


def test_forgot_password_unknown_email_returns_same_200_and_sends_nothing(anon_client, user, outbox):
    known = forgot(anon_client, user["email"])
    unknown = forgot(anon_client, _email("ghost"))

    assert unknown.status_code == known.status_code == 200
    assert unknown.json() == known.json()
    assert len(outbox) == 1  # solo el del usuario registrado


def test_forgot_password_ignores_inactive_users(anon_client, user, outbox):
    user_service.update_user(user["id"], {"is_active": False})
    assert forgot(anon_client, user["email"]).status_code == 200
    assert outbox == []


def test_forgot_password_is_rate_limited_per_user_but_still_returns_200(anon_client, user, outbox):
    for _ in range(config.PASSWORD_RESET_MAX_PER_HOUR + 2):
        assert forgot(anon_client, user["email"]).status_code == 200
    assert len(outbox) == config.PASSWORD_RESET_MAX_PER_HOUR


def test_reset_token_expires_within_configured_window(anon_client, user, outbox):
    token = request_reset_token(anon_client, outbox, user["email"])
    exp = datetime.fromtimestamp(security.decode_password_reset_token(token)["exp"], tz=timezone.utc)
    minutes = (exp - datetime.now(tz=timezone.utc)).total_seconds() / 60

    assert 15 <= config.PASSWORD_RESET_EXPIRE_MINUTES <= 60
    assert config.PASSWORD_RESET_EXPIRE_MINUTES - 1 < minutes <= config.PASSWORD_RESET_EXPIRE_MINUTES


# =========================================================
# POST /auth/reset-password
# =========================================================


def test_reset_password_updates_password_and_hashes_it(anon_client, user, outbox):
    token = request_reset_token(anon_client, outbox, user["email"])

    response = reset(anon_client, token)

    assert response.status_code == 200
    assert login(anon_client, user["email"], PASSWORD).status_code == 401
    assert login(anon_client, user["email"], NEW_PASSWORD).status_code == 200
    stored = user_service.get_user_by_id(user["id"])["hashed_password"]
    assert stored.startswith("$2") and NEW_PASSWORD not in stored


def test_reset_token_cannot_be_used_twice(anon_client, user, outbox):
    token = request_reset_token(anon_client, outbox, user["email"])
    assert reset(anon_client, token).status_code == 200

    second = reset(anon_client, token, "yet-another-password")

    assert second.status_code == 400
    assert second.json() == INVALID_TOKEN
    assert login(anon_client, user["email"], NEW_PASSWORD).status_code == 200


def test_using_one_reset_link_invalidates_the_other_pending_ones(anon_client, user, outbox):
    first = request_reset_token(anon_client, outbox, user["email"])
    second = request_reset_token(anon_client, outbox, user["email"])

    assert reset(anon_client, second).status_code == 200
    assert reset(anon_client, first, "yet-another-password").status_code == 400


def test_expired_reset_token_returns_400(anon_client, user):
    # Token bien firmado y registrado, pero con la expiración ya pasada.
    jti = str(uuid.uuid4())
    past = datetime.now(tz=timezone.utc) - timedelta(minutes=1)
    user_service.password_resets_table.insert(
        {"jti": jti, "user_id": user["id"], "created_at": past.isoformat(),
         "expires_at": past.isoformat(), "used_at": None}
    )
    token = create_password_reset_token(user["id"], jti, past)

    response = reset(anon_client, token)

    assert response.status_code == 400
    assert response.json() == INVALID_TOKEN
    assert login(anon_client, user["email"], PASSWORD).status_code == 200


def test_invalid_reset_tokens_return_400(anon_client, user, outbox):
    valid = request_reset_token(anon_client, outbox, user["email"])
    future = datetime.now(tz=timezone.utc) + timedelta(minutes=10)
    tokens = {
        "garbage": "not-a-token",
        "tampered": valid[:-4] + ("AAAA" if not valid.endswith("AAAA") else "BBBB"),
        # Firmado y vigente, pero nunca emitido por /forgot-password.
        "unregistered_jti": create_password_reset_token(user["id"], str(uuid.uuid4()), future),
        # Un token de sesión no sirve para restablecer la contraseña.
        "access_token": create_access_token(user["id"]),
    }
    for kind, token in tokens.items():
        response = reset(anon_client, token)
        assert response.status_code == 400, kind
    assert login(anon_client, user["email"], PASSWORD).status_code == 200


def test_reset_token_is_not_accepted_as_session_token(anon_client, user, outbox):
    token = request_reset_token(anon_client, outbox, user["email"])
    assert anon_client.get("/auth/me", headers=_bearer(token)).status_code == 401


@pytest.mark.parametrize("new_password", ["short", "x" * 73])
def test_reset_password_validates_new_password(anon_client, user, outbox, new_password):
    token = request_reset_token(anon_client, outbox, user["email"])
    assert reset(anon_client, token, new_password).status_code == 422
    # Un intento fallido por validación no consume el enlace.
    assert reset(anon_client, token).status_code == 200


# =========================================================
# POST /auth/change-password
# =========================================================


def change(client, headers, current_password, new_password=NEW_PASSWORD):
    return client.post(
        "/auth/change-password",
        json={"current_password": current_password, "new_password": new_password},
        headers=headers,
    )


def test_change_password_with_correct_current_password(anon_client, user):
    response = change(anon_client, user["headers"], PASSWORD)

    assert response.status_code == 200
    assert login(anon_client, user["email"], PASSWORD).status_code == 401
    assert login(anon_client, user["email"], NEW_PASSWORD).status_code == 200


def test_change_password_with_wrong_current_password_returns_400(anon_client, user):
    response = change(anon_client, user["headers"], "not-my-password")

    assert response.status_code == 400
    assert response.json() == {"detail": "Current password is incorrect"}
    assert login(anon_client, user["email"], PASSWORD).status_code == 200


def test_change_password_requires_session_token(anon_client):
    response = anon_client.post(
        "/auth/change-password", json={"current_password": PASSWORD, "new_password": NEW_PASSWORD}
    )
    assert response.status_code == 401


def test_change_password_validates_new_password(anon_client, user):
    assert change(anon_client, user["headers"], PASSWORD, "short").status_code == 422


def test_change_password_invalidates_pending_reset_links(anon_client, user, outbox):
    token = request_reset_token(anon_client, outbox, user["email"])
    assert change(anon_client, user["headers"], PASSWORD).status_code == 200
    assert reset(anon_client, token, "yet-another-password").status_code == 400


# =========================================================
# Email (Resend)
# =========================================================


def test_reset_email_is_sent_through_resend_with_mobile_friendly_link(monkeypatch):
    sent = []
    monkeypatch.setattr(config, "RESEND_API_KEY", "re_test_key")
    monkeypatch.setattr(resend.Emails, "send", lambda params: sent.append(params))

    email_service.send_password_reset_email("ana@trackflow.com", "the.reset.token")

    assert len(sent) == 1
    message = sent[0]
    link = "http://frontend.test/reset-password?token=the.reset.token"
    assert message["to"] == ["ana@trackflow.com"]
    assert message["from"] == config.EMAIL_FROM
    assert link in message["html"] and link in message["text"]
    assert 'name="viewport"' in message["html"]
    assert resend.api_key == "re_test_key"


def test_without_api_key_nothing_is_sent(monkeypatch):
    def fail(params):
        raise AssertionError("no debería llamarse a Resend sin API key")

    monkeypatch.setattr(config, "RESEND_API_KEY", "")
    monkeypatch.setattr(resend.Emails, "send", fail)

    email_service.send_password_reset_email("ana@trackflow.com", "token")


def test_provider_failure_does_not_break_forgot_password(anon_client, user, monkeypatch):
    def boom(params):
        raise RuntimeError("Resend caído")

    monkeypatch.setattr(config, "RESEND_API_KEY", "re_test_key")
    monkeypatch.setattr(resend.Emails, "send", boom)

    assert forgot(anon_client, user["email"]).status_code == 200


# =========================================================
# Auditoría de errores: el enlace no va al log y los envíos fallidos no cuentan
# =========================================================


def test_reset_link_is_not_logged_without_dev_flag(monkeypatch, caplog):
    monkeypatch.setattr(config, "RESEND_API_KEY", "")
    monkeypatch.setattr(config, "PASSWORD_RESET_LOG_LINK", False)

    with caplog.at_level("WARNING", logger="uvicorn.error"):
        sent = email_service.send_password_reset_email("ana@trackflow.com", "the.reset.token")

    assert sent is False
    assert "the.reset.token" not in caplog.text
    assert "ana@trackflow.com" not in caplog.text


def test_reset_link_is_logged_only_with_dev_flag(monkeypatch, caplog):
    monkeypatch.setattr(config, "RESEND_API_KEY", "")
    monkeypatch.setattr(config, "PASSWORD_RESET_LOG_LINK", True)

    with caplog.at_level("WARNING", logger="uvicorn.error"):
        sent = email_service.send_password_reset_email("ana@trackflow.com", "the.reset.token")

    assert sent is True
    assert "reset-password?token=the.reset.token" in caplog.text
    assert "ana@trackflow.com" not in caplog.text


def test_failed_reset_email_is_cancelled_and_does_not_count_towards_limit(anon_client, user, monkeypatch, caplog):
    def boom(params):
        raise RuntimeError("Resend caído")

    monkeypatch.setattr(config, "RESEND_API_KEY", "re_test_key")
    monkeypatch.setattr(resend.Emails, "send", boom)

    with caplog.at_level("ERROR", logger="uvicorn.error"):
        for _ in range(config.PASSWORD_RESET_MAX_PER_HOUR + 1):
            assert forgot(anon_client, user["email"]).status_code == 200

    pending = user_service.password_resets_table.count(user_service.ResetQuery.user_id == user["id"])
    assert pending == 0
    assert f"password_reset_email_failed user_id={user['id']}" in caplog.text
    assert user["email"] not in caplog.text
