"""Tareas de prueba con `base=TrackedTask` (hito 22).

Viven en un módulo propio (no en conftest.py) para que se registren una sola vez en la app de
Celery: una que falla N veces y luego funciona, otra que falla siempre, otra con un error que
no se reintenta y otra lenta.
"""

import threading
import time
from collections import defaultdict

from services.celery_app import app
from services.tasks.base import TrackedTask

# Intentos vistos por clave (cada test usa una clave propia), con el instante de cada uno.
ATTEMPTS: dict[str, list[float]] = defaultdict(list)
_lock = threading.Lock()


def _seen(key: str) -> int:
    with _lock:
        ATTEMPTS[key].append(time.monotonic())
        return len(ATTEMPTS[key])


class Boom(RuntimeError):
    """Fallo transitorio simulado."""


@app.task(bind=True, base=TrackedTask, name="tests.flaky")
def flaky(self, key: str, failures: int) -> dict:
    """Falla las `failures` primeras veces y después devuelve su resultado."""
    attempt = _seen(key)
    if attempt <= failures:
        raise Boom(f"fallo simulado {attempt} de {failures}")
    return {"key": key, "attempts": attempt}


@app.task(bind=True, base=TrackedTask, name="tests.always_fails")
def always_fails(self, key: str) -> None:
    attempt = _seen(key)
    raise Boom(f"fallo permanente, intento {attempt}")


class NotRetryable(ValueError):
    pass


@app.task(bind=True, base=TrackedTask, name="tests.bad_input", dont_retry_on=(NotRetryable,))
def bad_input(self, key: str) -> None:
    _seen(key)
    raise NotRetryable("parámetro inválido: no tiene sentido reintentar")


@app.task(bind=True, base=TrackedTask, name="tests.slow")
def slow(self, key: str, seconds: float) -> str:
    _seen(key)
    time.sleep(seconds)
    return "done"
