"""POST /auth/forgot-password — forgot_password, _send_reset_link y create_password_reset."""

from datetime import datetime, timedelta, timezone

from fastapi import BackgroundTasks

from services.api import config, email_service, security, user_service
from services.api.routes.auth import _send_reset_link, forgot_password
from services.api.user_models import ForgotPasswordRequest


def _pending(user_id):
    return user_service.password_resets_table.count(user_service.ResetQuery.user_id == user_id)


# =========================================================
# Camino feliz
# =========================================================


def test_forgot_password_queues_the_reset_link_instead_of_sending_inline(user, outbox):
    background_tasks = BackgroundTasks()

    result = forgot_password(ForgotPasswordRequest(email=user["email"]), background_tasks)

    assert result == {"message": "If that address is registered, you will receive a reset link shortly."}
    assert [(task.func, task.args) for task in background_tasks.tasks] == [(_send_reset_link, (user["email"],))]
    # Nada sale hasta que se ejecuta la tarea en segundo plano.
    assert outbox == []


def test_send_reset_link_emails_a_token_bound_to_the_user(user, outbox):
    _send_reset_link(user["email"])

    assert len(outbox) == 1
    to, token = outbox[0]
    assert to == user["email"]
    payload = security.decode_password_reset_token(token)
    assert payload["sub"] == user["id"]
    record = user_service.password_resets_table.get(user_service.ResetQuery.jti == payload["jti"])
    assert record["user_id"] == user["id"]
    assert record["used_at"] is None


def test_reset_token_expires_after_the_configured_window(user):
    _, token = user_service.create_password_reset(user["email"])

    exp = datetime.fromtimestamp(security.decode_password_reset_token(token)["exp"], tz=timezone.utc)
    minutes = (exp - datetime.now(tz=timezone.utc)).total_seconds() / 60

    assert config.PASSWORD_RESET_EXPIRE_MINUTES - 1 < minutes <= config.PASSWORD_RESET_EXPIRE_MINUTES


# =========================================================
# Casos límite
# =========================================================


def test_forgot_password_answers_the_same_for_unknown_email(user, new_email, outbox):
    ghost = new_email("ghost")

    known = forgot_password(ForgotPasswordRequest(email=user["email"]), BackgroundTasks())
    unknown = forgot_password(ForgotPasswordRequest(email=ghost), BackgroundTasks())
    _send_reset_link(ghost)

    assert unknown == known
    assert outbox == []


def test_send_reset_link_finds_the_user_regardless_of_email_case(user, outbox):
    _send_reset_link(user["email"].upper())

    assert [to for to, _ in outbox] == [user["email"]]


def test_reset_links_are_limited_per_user_and_hour(user):
    issued = [user_service.create_password_reset(user["email"]) for _ in range(config.PASSWORD_RESET_MAX_PER_HOUR)]

    assert all(result is not None for result in issued)
    assert user_service.create_password_reset(user["email"]) is None
    assert _pending(user["id"]) == config.PASSWORD_RESET_MAX_PER_HOUR


def test_reset_links_older_than_an_hour_do_not_count_towards_the_limit(user, monkeypatch):
    real_now = user_service._now
    monkeypatch.setattr(user_service, "_now", lambda: real_now() - timedelta(minutes=61))
    for _ in range(config.PASSWORD_RESET_MAX_PER_HOUR):
        assert user_service.create_password_reset(user["email"]) is not None
    monkeypatch.setattr(user_service, "_now", real_now)

    assert user_service.create_password_reset(user["email"]) is not None
    # Los caducados se purgan al emitir el nuevo.
    assert _pending(user["id"]) == 1


def test_rate_limit_of_one_user_does_not_affect_another(user, make_user):
    other = make_user()
    for _ in range(config.PASSWORD_RESET_MAX_PER_HOUR):
        user_service.create_password_reset(user["email"])

    assert user_service.create_password_reset(other["email"]) is not None


# =========================================================
# Modos de fallo
# =========================================================


def test_send_reset_link_ignores_inactive_users(user, outbox):
    user_service.update_user(user["id"], {"is_active": False})

    _send_reset_link(user["email"])

    assert outbox == []
    assert _pending(user["id"]) == 0


def test_failed_email_cancels_the_link_and_logs_only_the_user_id(user, monkeypatch, caplog):
    monkeypatch.setattr(email_service, "send_password_reset_email", lambda to, token: False)

    with caplog.at_level("ERROR", logger="uvicorn.error"):
        for _ in range(config.PASSWORD_RESET_MAX_PER_HOUR + 1):
            _send_reset_link(user["email"])

    # Ningún intento fallido cuenta para el límite por hora.
    assert _pending(user["id"]) == 0
    assert f"password_reset_email_failed user_id={user['id']}" in caplog.text
    assert user["email"] not in caplog.text


def test_cancel_password_reset_with_unreadable_token_does_nothing(user):
    _, token = user_service.create_password_reset(user["email"])

    user_service.cancel_password_reset("not-a-token")
    user_service.cancel_password_reset(security.create_access_token(user["id"]))

    assert _pending(user["id"]) == 1
    assert security.decode_password_reset_token(token) is not None
