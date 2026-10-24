"""services/api/cache.py: TTL, HIT / MISS, invalidación, claves y logs, sin HTTP.

El reloj de la caché se sustituye por uno manual: la caducidad se comprueba avanzándolo,
sin esperar segundos reales.
"""

import logging

import pytest

from services.api import cache
from services.api.cache import TTLCache, make_key


@pytest.fixture
def clock(monkeypatch):
    """Reloj manual: `clock.now` es el instante actual y se avanza a mano."""

    class Clock:
        now = 1000.0

    monkeypatch.setattr(cache, "_clock", lambda: Clock.now)
    return Clock


@pytest.fixture
def cache_logs(caplog, monkeypatch):
    """Mensajes de "api.cache". main.py corta la propagación del logger "api" hacia la raíz,
    que es donde escucha caplog: durante el test se vuelve a activar."""
    monkeypatch.setattr(logging.getLogger("api"), "propagate", True)
    caplog.set_level(logging.INFO, logger="api.cache")
    return lambda: [record.getMessage() for record in caplog.records if record.name == "api.cache"]


@pytest.fixture
def counted():
    """Función cara simulada que cuenta cuántas veces se calcula de verdad."""

    class Counted:
        calls = 0

        def __call__(self):
            self.calls += 1
            return f"valor {self.calls}"

    return Counted()


# =========================================================
# HIT / MISS y TTL
# =========================================================


def test_first_read_is_a_miss_and_second_a_hit(clock, counted, cache_logs):
    store = TTLCache()

    assert store.get_or_set("/a", 60, counted) == "valor 1"
    assert store.get_or_set("/a", 60, counted) == "valor 1"

    assert counted.calls == 1
    assert cache_logs() == ["MISS /a", "HIT /a"]


def test_entry_is_served_until_the_ttl_and_recomputed_after(clock, counted):
    store = TTLCache()
    store.get_or_set("/a", 60, counted)

    clock.now += 59.9
    assert store.get_or_set("/a", 60, counted) == "valor 1"

    clock.now += 0.1  # justo a los 60 s ya ha caducado
    assert store.get_or_set("/a", 60, counted) == "valor 2"
    assert counted.calls == 2


@pytest.mark.parametrize("ttl", [0, -5])
def test_every_entry_needs_a_positive_ttl(ttl):
    with pytest.raises(ValueError):
        TTLCache().set("/a", "valor", ttl)


def test_falsy_values_are_cached_too(clock):
    # Una lista vacía es una respuesta válida (p. ej. sin duplicados) y también se cachea.
    store = TTLCache()
    calls = []

    store.get_or_set("/a", 60, lambda: calls.append(1) or [])
    store.get_or_set("/a", 60, lambda: calls.append(1) or [])

    assert calls == [1]


def test_an_error_is_not_cached(clock, counted):
    store = TTLCache()

    def failing():
        raise RuntimeError("base de datos caída")

    with pytest.raises(RuntimeError):
        store.get_or_set("/a", 60, failing)

    assert store.get_or_set("/a", 60, counted) == "valor 1"


# =========================================================
# Invalidación
# =========================================================


def test_invalidate_removes_only_that_key(clock, counted, cache_logs):
    store = TTLCache()
    store.set("/a", "viejo", 60)
    store.set("/b", "b", 60)

    store.invalidate("/a")

    assert store.get_or_set("/a", 60, counted) == "valor 1"
    assert store.get_or_set("/b", 60, counted) == "b"
    assert "INVALIDATE /a (1 entradas)" in cache_logs()


def test_invalidate_prefix_removes_every_matching_key(clock):
    store = TTLCache()
    for key in ["/inventory/products", "/inventory/orders", "/inventory/products|scope=u1", "/suppliers"]:
        store.set(key, key, 60)

    store.invalidate_prefix("/inventory/")

    assert store.get("/inventory/products") is cache._MISSING
    assert store.get("/inventory/orders") is cache._MISSING
    assert store.get("/inventory/products|scope=u1") is cache._MISSING
    assert store.get("/suppliers") == "/suppliers"


# =========================================================
# Claves
# =========================================================


def test_query_params_are_sorted_and_normalized():
    assert make_key("/api/incidents", {"status": "open", "branch": "central"}) == make_key(
        "/api/incidents", {"branch": " central ", "status": "open", "category": "", "origin": None}
    )
    assert make_key("/api/incidents", {"status": "open", "branch": "central"}) == (
        "/api/incidents?branch=central&status=open"
    )


def test_different_params_are_different_keys():
    assert make_key("/api/incidents", {"status": "open"}) != make_key("/api/incidents", {"status": "resolved"})


def test_path_without_params_ignores_the_trailing_slash():
    assert make_key("/inventory/products/") == make_key("/inventory/products") == "/inventory/products"


def test_different_users_never_share_an_entry(clock):
    # Una respuesta personalizada lleva el id del usuario en la clave: lo que se guarda para
    # uno no se le sirve nunca a otro.
    store = TTLCache()
    store.set(make_key("/auth/me", scope="user-1"), {"email": "ana@trackflow.com"}, 60)

    assert store.get(make_key("/auth/me", scope="user-2")) is cache._MISSING
    assert store.get(make_key("/auth/me", scope="user-1")) == {"email": "ana@trackflow.com"}
