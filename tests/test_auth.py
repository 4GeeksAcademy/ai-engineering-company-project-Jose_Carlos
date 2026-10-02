"""Tests de AUTH-01: usuarios, perfiles, login JWT y protección de rutas."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from jose import jwt

from services.api import config, user_service
from services.api.security import create_access_token
from services.api.user_models import UserRole

PASSWORD = "s3cret-password"


def _email(prefix="user"):
    return f"{prefix}-{uuid.uuid4().hex[:8]}@trackflow.com"


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


def register(client, email=None, password=PASSWORD, **profile):
    response = client.post("/users", json={"email": email or _email(), "password": password, **profile})
    assert response.status_code == 201, response.text
    return response.json()


def login(client, email, password=PASSWORD):
    return client.post("/auth/login", json={"email": email, "password": password})


def token_for(client, email, password=PASSWORD):
    response = login(client, email, password)
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


@pytest.fixture
def alice(anon_client):
    user = register(anon_client, name="Alice", phone="+34 600 000 001", address="Calle Mayor 1")
    return {**user, "headers": _bearer(token_for(anon_client, user["email"]))}


@pytest.fixture
def bob(anon_client):
    user = register(anon_client, name="Bob")
    return {**user, "headers": _bearer(token_for(anon_client, user["email"]))}


@pytest.fixture
def admin(anon_client):
    email = _email("admin")
    user, _ = user_service.create_user(email, PASSWORD, role=UserRole.ADMIN)
    return {**user, "headers": _bearer(token_for(anon_client, email))}


# =========================================================
# Registro: POST /users
# =========================================================


def test_register_creates_user_with_default_role_and_linked_profile(anon_client):
    email = _email()
    body = register(anon_client, email=email, name="Ana", phone="123", address="Madrid")

    assert body["email"] == email
    assert body["role"] == "user"
    assert body["is_active"] is True
    assert "hashed_password" not in body and "password" not in body
    assert body["profile"]["user_id"] == body["id"]
    assert {k: body["profile"][k] for k in ("name", "phone", "address")} == {
        "name": "Ana", "phone": "123", "address": "Madrid",
    }


def test_register_ignores_role_sent_by_client(anon_client):
    body = register(anon_client, role="admin")
    assert body["role"] == "user"


def test_user_record_stores_only_credentials_and_hashed_password(anon_client):
    body = register(anon_client, name="Solo En Perfil", phone="999")
    stored = user_service.users_table.get(user_service.UserQuery.id == body["id"])

    assert set(stored) == {"id", "email", "hashed_password", "is_active", "role", "created_at"}
    assert stored["hashed_password"] != PASSWORD
    assert stored["hashed_password"].startswith("$2")  # bcrypt
    assert PASSWORD not in str(user_service.users_table.all())


def test_register_duplicate_email_returns_409(anon_client):
    email = _email()
    register(anon_client, email=email)
    response = anon_client.post("/users", json={"email": email.upper(), "password": PASSWORD})
    assert response.status_code == 409


@pytest.mark.parametrize("payload", [
    {"email": "not-an-email", "password": PASSWORD},
    {"email": "a@trackflow.com", "password": "short"},
    {"email": "a@trackflow.com", "password": "x" * 73},
])
def test_register_rejects_invalid_payload(anon_client, payload):
    assert anon_client.post("/users", json=payload).status_code == 422


def test_role_enum_rejects_unknown_values(admin, bob, anon_client):
    response = anon_client.put(f"/users/{bob['id']}", json={"role": "superuser"}, headers=admin["headers"])
    assert response.status_code == 422


# =========================================================
# Login y token
# =========================================================


def test_login_returns_signed_jwt_with_user_id(anon_client, alice):
    response = login(anon_client, alice["email"])

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == config.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    claims = jwt.decode(body["access_token"], config.JWT_SECRET_KEY, algorithms=[config.JWT_ALGORITHM])
    assert claims["sub"] == alice["id"]
    assert "exp" in claims


@pytest.mark.parametrize("email_kind,password", [("known", "wrong-password"), ("unknown", PASSWORD)])
def test_login_with_bad_credentials_returns_401(anon_client, alice, email_kind, password):
    email = alice["email"] if email_kind == "known" else _email("ghost")
    response = login(anon_client, email, password)
    assert response.status_code == 401
    assert response.json() == {"detail": "Incorrect email or password"}


def test_oauth2_form_login_used_by_docs_authorize(anon_client, alice):
    response = anon_client.post("/auth/token", data={"username": alice["email"], "password": PASSWORD})
    assert response.status_code == 200
    assert response.json()["access_token"]


def test_inactive_user_cannot_login_nor_use_token(anon_client, admin, bob):
    anon_client.put(f"/users/{bob['id']}", json={"is_active": False}, headers=admin["headers"])

    assert login(anon_client, bob["email"]).status_code == 401
    assert anon_client.get("/auth/me", headers=bob["headers"]).status_code == 401


def test_auth_me_returns_email_role_and_profile(anon_client, alice):
    response = anon_client.get("/auth/me", headers=alice["headers"])

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == alice["email"]
    assert body["role"] == "user"
    assert body["profile"]["name"] == "Alice"
    assert body["profile"]["phone"] == "+34 600 000 001"


# =========================================================
# 401: sin token, token mal formado, expirado o de usuario borrado
# =========================================================

PROTECTED = [
    ("get", "/auth/me"),
    ("get", "/users"),
    ("get", "/users/some-id"),
    ("put", "/users/some-id"),
    ("delete", "/users/some-id"),
    ("get", "/profiles/me"),
    ("put", "/profiles/me"),
    ("post", "/analyze"),
    ("get", "/api/incidents/results/export"),
    ("get", "/suppliers"),
    ("post", "/suppliers"),
    ("get", "/suppliers/1"),
    ("patch", "/suppliers/1/rate"),
    ("patch", "/suppliers/1/status"),
    ("delete", "/suppliers/1"),
]


def _expired_token(user_id):
    return create_access_token(user_id, expires_minutes=-1)


def _bad_tokens(user_id):
    now = datetime.now(tz=timezone.utc)
    forged = jwt.encode({"sub": user_id, "exp": now + timedelta(minutes=5)}, "wrong-secret", algorithm="HS256")
    no_sub = jwt.encode({"exp": now + timedelta(minutes=5)}, config.JWT_SECRET_KEY, algorithm="HS256")
    return {
        "expired": _expired_token(user_id),
        "malformed": "not.a.jwt",
        "garbage": "abc",
        "wrong_signature": forged,
        "missing_sub": no_sub,
        "unknown_user": create_access_token(str(uuid.uuid4())),
    }


@pytest.mark.parametrize("method,path", PROTECTED)
def test_protected_routes_without_token_return_401(anon_client, method, path):
    response = anon_client.request(method, path)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize("kind", ["expired", "malformed", "garbage", "wrong_signature", "missing_sub", "unknown_user"])
@pytest.mark.parametrize("method,path", PROTECTED)
def test_protected_routes_with_invalid_token_return_401(anon_client, alice, method, path, kind):
    token = _bad_tokens(alice["id"])[kind]
    assert anon_client.request(method, path, headers=_bearer(token)).status_code == 401


def test_deleted_user_token_stops_working(anon_client, bob):
    assert anon_client.delete(f"/users/{bob['id']}", headers=bob["headers"]).status_code == 200
    assert anon_client.get("/auth/me", headers=bob["headers"]).status_code == 401


def test_public_routes_stay_public(anon_client):
    assert anon_client.get("/").status_code == 200
    assert anon_client.get("/backoffice/").status_code == 200


# =========================================================
# 403: acceso a recursos de otro usuario
# =========================================================


def test_user_cannot_read_update_or_delete_another_user(anon_client, alice, bob):
    url = f"/users/{bob['id']}"
    assert anon_client.get(url, headers=alice["headers"]).status_code == 403
    assert anon_client.put(url, json={"email": _email()}, headers=alice["headers"]).status_code == 403
    assert anon_client.delete(url, headers=alice["headers"]).status_code == 403
    assert user_service.get_user_by_id(bob["id"])["email"] == bob["email"]


def test_user_cannot_read_or_update_another_profile(anon_client, alice, bob):
    url = f"/profiles/{bob['id']}"
    assert anon_client.get(url, headers=alice["headers"]).status_code == 403
    assert anon_client.put(url, json={"name": "Hacked"}, headers=alice["headers"]).status_code == 403
    assert user_service.get_profile_by_user_id(bob["id"])["name"] == "Bob"


def test_non_admin_cannot_list_users_or_change_role(anon_client, alice):
    assert anon_client.get("/users", headers=alice["headers"]).status_code == 403
    response = anon_client.put(f"/users/{alice['id']}", json={"role": "admin"}, headers=alice["headers"])
    assert response.status_code == 403
    assert user_service.get_user_by_id(alice["id"])["role"] == "user"


# =========================================================
# CRUD como dueño / admin
# =========================================================


def test_user_reads_and_updates_own_credentials(anon_client, alice):
    url = f"/users/{alice['id']}"
    assert anon_client.get(url, headers=alice["headers"]).json()["email"] == alice["email"]

    new_email, new_password = _email("alice-new"), "another-password"
    response = anon_client.put(url, json={"email": new_email, "password": new_password}, headers=alice["headers"])
    assert response.status_code == 200
    assert response.json()["email"] == new_email

    assert login(anon_client, alice["email"]).status_code == 401
    assert login(anon_client, new_email, new_password).status_code == 200


def test_update_to_taken_email_returns_409(anon_client, alice, bob):
    response = anon_client.put(f"/users/{alice['id']}", json={"email": bob["email"]}, headers=alice["headers"])
    assert response.status_code == 409


def test_admin_lists_reads_and_changes_role(anon_client, admin, bob):
    listed = anon_client.get("/users", headers=admin["headers"])
    assert listed.status_code == 200
    assert bob["id"] in {u["id"] for u in listed.json()}
    assert all("hashed_password" not in u for u in listed.json())

    assert anon_client.get(f"/users/{bob['id']}", headers=admin["headers"]).status_code == 200
    response = anon_client.put(f"/users/{bob['id']}", json={"role": "manager"}, headers=admin["headers"])
    assert response.status_code == 200
    assert response.json()["role"] == "manager"


def test_admin_can_read_and_update_any_profile(anon_client, admin, bob):
    response = anon_client.put(f"/profiles/{bob['id']}", json={"phone": "555"}, headers=admin["headers"])
    assert response.status_code == 200
    assert response.json()["phone"] == "555"
    assert anon_client.get(f"/profiles/{bob['id']}", headers=admin["headers"]).json()["name"] == "Bob"


def test_delete_user_also_deletes_profile(anon_client, admin, bob):
    response = anon_client.delete(f"/users/{bob['id']}", headers=admin["headers"])

    assert response.status_code == 200
    assert user_service.get_user_by_id(bob["id"]) is None
    assert user_service.get_profile_by_user_id(bob["id"]) is None
    assert anon_client.get(f"/users/{bob['id']}", headers=admin["headers"]).status_code == 404


def test_profiles_me_read_and_partial_update(anon_client, alice):
    me = anon_client.get("/profiles/me", headers=alice["headers"])
    assert me.status_code == 200
    assert me.json()["user_id"] == alice["id"]

    response = anon_client.put("/profiles/me", json={"name": "Alice B."}, headers=alice["headers"])
    assert response.status_code == 200
    assert response.json()["name"] == "Alice B."
    assert response.json()["phone"] == "+34 600 000 001"  # no enviado → sin cambios

    # El perfil vive en Profile, no en User.
    assert "name" not in user_service.get_user_by_id(alice["id"])


# =========================================================
# Rutas existentes con token válido (sin regresiones)
# =========================================================


def test_protected_supplier_routes_work_with_valid_token(anon_client, alice):
    supplier = {
        "name": f"Carrier {uuid.uuid4().hex[:6]}", "country": "Spain", "categories": ["carrier_last_mile"],
        "rate_per_shipment": 4.5, "currency": "EUR", "status": "active",
    }
    created = anon_client.post("/suppliers", json=supplier, headers=alice["headers"])
    assert created.status_code == 201
    supplier_id = created.json()["id"]

    assert anon_client.get(f"/suppliers/{supplier_id}", headers=alice["headers"]).status_code == 200
    assert anon_client.patch(f"/suppliers/{supplier_id}/rate", json={"rate_per_shipment": 5}, headers=alice["headers"]).status_code == 200
    assert anon_client.delete(f"/suppliers/{supplier_id}", headers=alice["headers"]).status_code == 200
