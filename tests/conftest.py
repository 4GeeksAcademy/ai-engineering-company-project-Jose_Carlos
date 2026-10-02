import os
import shutil
import tempfile

import pytest
from fastapi.testclient import TestClient

# main importa services/api/store.py, que abre TinyDB al importarse: lo apuntamos a un
# directorio desechable ANTES del import para no crear nunca services/api/db.json.
_test_db_dir = tempfile.mkdtemp(prefix="trackflow-tests-")
os.environ["TINYDB_PATH"] = os.path.join(_test_db_dir, "db.json")

import services.api.main as main  # noqa: E402
from services.api import store  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def remove_test_db_dir():
    yield
    store.db.close()
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
def client():
    return TestClient(main.app)
