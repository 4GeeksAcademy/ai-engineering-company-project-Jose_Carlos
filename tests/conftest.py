import os
import shutil
import tempfile

import pytest
from fastapi.testclient import TestClient

# main importa services/api/store.py, que abre TinyDB al importarse: lo apuntamos a un
# directorio desechable ANTES del import para no crear nunca services/api/db.json.
_test_db_dir = tempfile.mkdtemp(prefix="trackflow-tests-")
os.environ["TINYDB_PATH"] = os.path.join(_test_db_dir, "db.json")
# Config JWT de pruebas: nunca se usa el .env local (las variables del entorno tienen prioridad).
os.environ["JWT_SECRET_KEY"] = "test-only-secret-key-not-for-production"
os.environ["JWT_ALGORITHM"] = "HS256"
os.environ["ACCESS_TOKEN_EXPIRE_MINUTES"] = "30"
# Sin API key de Resend: los tests nunca envían correos reales aunque el .env local tenga una.
os.environ["RESEND_API_KEY"] = ""
os.environ["FRONTEND_URL"] = "http://frontend.test"
os.environ["PASSWORD_RESET_EXPIRE_MINUTES"] = "30"
os.environ["PASSWORD_RESET_MAX_PER_HOUR"] = "3"
# Embeddings por hashing: deterministas y sin descargar ningún modelo durante los tests.
os.environ["EMBEDDINGS_PROVIDER"] = "hashing"

import services.api.main as main  # noqa: E402
from services.api import email_service, security, store, user_service  # noqa: E402
from services.api.security import create_access_token  # noqa: E402

# bcrypt con coste mínimo en tests (sigue siendo bcrypt real, solo más rápido).
security.bcrypt = security.bcrypt.using(rounds=4)


@pytest.fixture(scope="session", autouse=True)
def remove_test_db_dir():
    yield
    store.db.close()
    store.embeddings_db.close()
    shutil.rmtree(_test_db_dir, ignore_errors=True)


@pytest.fixture(autouse=True)
def isolated_api(tmp_path, monkeypatch):
    # /analyze escribe un NamedTemporaryFile(delete=False) en el temp del sistema:
    # lo redirigimos a un directorio desechable de pytest.
    api_tmp = tmp_path / "api_tmp"
    api_tmp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(api_tmp))

    # Estado global del módulo: cada test parte sin análisis previo y se restaura al terminar.
    monkeypatch.setattr(main, "last_analysis", None)

    return api_tmp


@pytest.fixture
def outbox(monkeypatch):
    """Correos de restablecimiento "enviados": lista de (destinatario, token)."""
    sent = []
    monkeypatch.setattr(
        email_service, "send_password_reset_email", lambda to, token: sent.append((to, token))
    )
    return sent


@pytest.fixture(scope="session")
def auth_headers():
    """Cabecera Authorization de un usuario normal (role user) creado una vez por sesión."""
    user, _ = user_service.create_user("tests-default@trackflow.com", "tests-password")
    return {"Authorization": f"Bearer {create_access_token(user['id'])}"}


@pytest.fixture
def client(auth_headers):
    # Cliente autenticado: las rutas protegidas deben seguir funcionando con un token válido.
    return TestClient(main.app, headers=auth_headers)


@pytest.fixture
def anon_client():
    # Cliente sin cabecera Authorization.
    return TestClient(main.app)
