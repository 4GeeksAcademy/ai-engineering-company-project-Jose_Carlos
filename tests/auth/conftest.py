"""Fixtures de las pruebas unitarias de autenticación (AUTH-088).

Estas pruebas llaman directamente a las funciones de ruta y a los servicios: no pasan
por TestClient ni por la serialización HTTP.
"""

import uuid

import pytest

from services.api import user_service

PASSWORD = "s3cret-password"


@pytest.fixture
def password():
    return PASSWORD


@pytest.fixture
def new_email():
    """Fábrica de emails únicos: la base TinyDB se comparte entre tests de la sesión."""
    return lambda prefix="unit": f"{prefix}-{uuid.uuid4().hex[:10]}@trackflow.com"


@pytest.fixture
def make_user(new_email):
    def _make(password=PASSWORD, **kwargs):
        user, _ = user_service.create_user(new_email(), password, **kwargs)
        return user

    return _make


@pytest.fixture
def user(make_user):
    return make_user()
