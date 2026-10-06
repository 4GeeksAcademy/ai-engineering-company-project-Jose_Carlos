"""Embeddings de texto para la capa semántica del gestor de incidencias.

Dos proveedores, elegidos con EMBEDDINGS_PROVIDER:

- "fastembed" (por defecto): modelo multilingüe local (ONNX, sin API key). Entiende el
  significado, así que una búsqueda en español encuentra incidencias redactadas en inglés.
  La primera vez descarga el modelo (~220 MB) a la caché de fastembed.
- "hashing": vectores por hashing de palabras y trigramas. No necesita descargar nada y es
  determinista, pero solo capta parecido léxico. Lo usan los tests y es el plan B si el
  modelo no se puede cargar (sin red, por ejemplo).
"""

import logging
import os
import re
import threading
import time
import unicodedata
import zlib
from pathlib import Path

import numpy as np


logger = logging.getLogger(__name__)

DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


def _normalize(matrix: np.ndarray) -> np.ndarray:
    """Normaliza cada fila a longitud 1: así el producto escalar es la similitud coseno."""
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


class HashingEmbedder:
    name = "hashing-v1"
    dimensions = 512
    # Umbrales de similitud coseno calibrados para este proveedor.
    min_score = 0.2          # por debajo no se considera relacionado
    triage_score = 0.3       # mínimo para que una incidencia vote la categoría sugerida
    duplicate_score = 0.85   # a partir de aquí es un posible duplicado

    def embed(self, texts: list[str]) -> np.ndarray:
        matrix = np.zeros((len(texts), self.dimensions), dtype=np.float32)
        for row, text in enumerate(texts):
            for feature in self._features(text):
                matrix[row, zlib.crc32(feature.encode("utf-8")) % self.dimensions] += 1.0
        return _normalize(matrix)

    @staticmethod
    def _features(text: str) -> list[str]:
        # Minúsculas y sin acentos: "envío" y "envio" deben coincidir.
        plain = unicodedata.normalize("NFKD", text.lower())
        plain = "".join(char for char in plain if not unicodedata.combining(char))
        words = re.findall(r"[a-z0-9]+", plain)
        trigrams = [word[i:i + 3] for word in words for i in range(len(word) - 2)]
        return words + trigrams


class FastEmbedEmbedder:
    # Calibrados con el histórico del seed: una consulta sin relación queda en ~0.2, una
    # relacionada (aunque esté en otro idioma) en 0.4-0.7 y el mismo problema por encima de 0.9.
    min_score = 0.35
    triage_score = 0.5
    duplicate_score = 0.9

    def __init__(self, model_name: str):
        from fastembed import TextEmbedding

        # Caché estable: por defecto fastembed usa el directorio temporal, que el sistema puede vaciar.
        cache_dir = os.getenv("EMBEDDINGS_CACHE_DIR") or str(Path.home() / ".cache" / "fastembed")
        self._model = TextEmbedding(model_name=model_name, cache_dir=cache_dir)
        self.name = f"fastembed:{model_name}"

    def embed(self, texts: list[str]) -> np.ndarray:
        return _normalize(np.array(list(self._model.embed(texts)), dtype=np.float32))


class EmbeddingsUnavailable(Exception):
    """El proveedor de embeddings no ha podido calcular los vectores."""


# Fallos esperables al cargar o usar el modelo: paquete ausente, sin red o sin disco,
# nombre de modelo desconocido y errores del runtime ONNX (derivan de RuntimeError).
PROVIDER_ERRORS = (ImportError, OSError, ValueError, RuntimeError)

# Si el modelo no carga se usa "hashing" y se vuelve a intentar pasado este tiempo.
FALLBACK_RETRY_SECONDS = 600

_embedder = None
_fallback_since = None
_embedder_lock = threading.Lock()


def get_embedder():
    """Devuelve el proveedor de embeddings (se crea una sola vez por proceso).

    Si el modelo configurado no se puede cargar se usa "hashing" como plan B y se
    reintenta la carga cada FALLBACK_RETRY_SECONDS; mientras tanto `is_degraded()` es True.
    """
    global _embedder, _fallback_since
    with _embedder_lock:
        retry_due = (
            _fallback_since is not None
            and time.monotonic() - _fallback_since >= FALLBACK_RETRY_SECONDS
        )
        if _embedder is not None and not retry_due:
            return _embedder

        provider = os.getenv("EMBEDDINGS_PROVIDER", "fastembed").strip().lower()
        if provider == "hashing":
            _embedder = HashingEmbedder()
            _fallback_since = None
            return _embedder

        try:
            _embedder = FastEmbedEmbedder(os.getenv("EMBEDDINGS_MODEL", DEFAULT_MODEL))
            _fallback_since = None
        except PROVIDER_ERRORS:
            logger.exception(
                "No se pudo cargar el modelo de embeddings; se usa el proveedor 'hashing' "
                "y se reintentará en %s segundos.",
                FALLBACK_RETRY_SECONDS,
            )
            _embedder = HashingEmbedder()
            _fallback_since = time.monotonic()
        return _embedder


def is_degraded() -> bool:
    """True si se está usando el plan B porque el modelo configurado no ha cargado."""
    return _fallback_since is not None


def embed(texts: list[str], embedder=None) -> np.ndarray:
    """Calcula los vectores; un fallo del proveedor se convierte en EmbeddingsUnavailable."""
    embedder = embedder or get_embedder()
    try:
        return embedder.embed(texts)
    except PROVIDER_ERRORS as error:
        raise EmbeddingsUnavailable("El proveedor de embeddings ha fallado") from error
