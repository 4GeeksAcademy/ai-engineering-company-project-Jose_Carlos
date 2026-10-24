"""Caché en memoria con caducidad (TTL) para respuestas de lectura caras.

- Vive en la memoria del proceso: se pierde al reiniciar y cada worker de uvicorn tiene la
  suya (hoy se arranca con uno solo). Sin Redis ni infraestructura nueva.
- Toda entrada caduca: `set` exige un TTL en segundos, no hay entradas "para siempre".
- Las escrituras que cambian los datos la invalidan (por clave o por prefijo) justo después
  de guardar, para que la siguiente lectura los vuelva a calcular.
- Las rutas síncronas de FastAPI se ejecutan en varios hilos a la vez (threadpool): un lock
  protege el diccionario para que dos peticiones no lo lean y modifiquen a la vez.
- Los valores guardados se comparten entre peticiones: quien los lee no debe modificarlos.

Claves (`make_key`): ruta + parámetros de consulta ordenados y normalizados. Si la respuesta
depende del usuario, su id va en `scope`; una clave compartida con datos privados de un
usuario sería una fuga de datos hacia los demás.
"""

import logging
import threading
import time
from urllib.parse import urlencode


logger = logging.getLogger("api.cache")

# Reloj monotónico: no salta si cambia la hora del sistema. Los tests lo sustituyen para
# comprobar la caducidad sin esperar.
_clock = time.monotonic

_MISSING = object()


class TTLCache:
    def __init__(self):
        self._entries: dict[str, tuple[object, float]] = {}  # clave -> (valor, instante de caducidad)
        self._lock = threading.Lock()

    def get(self, key: str):
        """El valor guardado, o `_MISSING` si no existe o ha caducado (se borra al leerlo)."""
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None and _clock() >= entry[1]:
                del self._entries[key]
                entry = None
        if entry is None:
            logger.info(f"MISS {key}")
            return _MISSING
        logger.info(f"HIT {key}")
        return entry[0]

    def set(self, key: str, value, ttl_seconds: float) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds debe ser mayor que 0: toda entrada de la caché caduca")
        with self._lock:
            self._entries[key] = (value, _clock() + ttl_seconds)

    def get_or_set(self, key: str, ttl_seconds: float, compute):
        """Devuelve el valor cacheado o lo calcula con `compute()` y lo guarda.

        Si `compute` lanza una excepción no se guarda nada: un error no se cachea.
        El cálculo va fuera del lock para no bloquear las demás claves mientras dura.
        """
        value = self.get(key)
        if value is _MISSING:
            value = compute()
            self.set(key, value, ttl_seconds)
        return value

    def invalidate(self, key: str) -> None:
        with self._lock:
            removed = self._entries.pop(key, None) is not None
        logger.info(f"INVALIDATE {key} ({int(removed)} entradas)")

    def invalidate_prefix(self, prefix: str) -> None:
        with self._lock:
            keys = [key for key in self._entries if key.startswith(prefix)]
            for key in keys:
                del self._entries[key]
        logger.info(f"INVALIDATE {prefix}* ({len(keys)} entradas)")

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


def make_key(path: str, params: dict | None = None, scope: str | None = None) -> str:
    """Clave estable para una petición de lectura.

    - `params`: se ordenan por nombre y se descartan los vacíos, así `?b=2&a=1`, `?a=1&b=2`
      y `?a=1&b=2&c=` comparten entrada. Los valores se recortan y se pasan a texto.
    - `scope`: id del usuario o del cliente si la respuesta depende de él.
    """
    normalized = sorted(
        (name, str(value).strip())
        for name, value in (params or {}).items()
        if value is not None and str(value).strip() != ""
    )
    key = path.rstrip("/") or "/"
    if normalized:
        key += "?" + urlencode(normalized)
    if scope is not None:
        # Al final, no al principio: así invalidate_prefix("/ruta") borra las de todos los usuarios.
        key += f"|scope={scope}"
    return key


# Una sola caché para toda la API.
response_cache = TTLCache()
