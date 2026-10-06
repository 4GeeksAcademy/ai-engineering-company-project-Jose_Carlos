"""Capa semántica del gestor de incidencias: similares, búsqueda, duplicados y triaje.

Cada incidencia tiene un embedding de su título y descripción. Con ~cientos de incidencias
la similitud coseno se calcula en memoria con NumPy; no hace falta una base de datos
vectorial. El CRUD no depende de esto: si los embeddings fallan, las incidencias se crean
y se listan igual.
"""

import hashlib
import logging
from collections import defaultdict

import numpy as np

from services.api import store
from services.api.embeddings import EmbeddingsUnavailable, embed, get_embedder, is_degraded


logger = logging.getLogger(__name__)

ACTIVE_STATUSES = ("open", "in_progress")

# Triaje: vecinos que votan la categoría y confianza mínima para sugerirla.
TRIAGE_NEIGHBOURS = 5
TRIAGE_MIN_CONFIDENCE = 0.5


def incident_text(title: str, description: str) -> str:
    """Texto que se convierte en embedding."""
    title = (title or "").strip()
    description = (description or "").strip()
    # En el seed el título es el principio de la descripción: no lo repetimos.
    if not title or description.startswith(title):
        return description
    return f"{title}\n{description}"


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _pending(embedder) -> list[tuple[int, str]]:
    """Incidencias (id, texto) sin embedding al día para este proveedor."""
    stored = {record["incident_id"]: record for record in store.get_incident_embeddings()}

    pending = []
    for incident in store.get_all_incidents():
        text = incident_text(incident["title"], incident["description"])
        record = stored.get(incident["id"])
        if record is None or record["model"] != embedder.name or record["text_hash"] != _text_hash(text):
            pending.append((incident["id"], text))
    return pending


def ensure_index() -> int:
    """Calcula los embeddings que falten (o estén obsoletos). Devuelve cuántos ha calculado."""
    embedder = get_embedder()
    pending = _pending(embedder)

    if pending:
        vectors = embed([text for _, text in pending], embedder)
        store.save_incident_embeddings(
            [
                {
                    "incident_id": incident_id,
                    "model": embedder.name,
                    "text_hash": _text_hash(text),
                    "vector": [round(float(value), 6) for value in vector],
                }
                for (incident_id, text), vector in zip(pending, vectors)
            ]
        )
    return len(pending)


def index_pending() -> None:
    """Indexa lo pendiente en segundo plano, tras crear una incidencia.

    Si el proveedor de embeddings falla, la incidencia queda pendiente y se indexa en la
    siguiente búsqueda; `semantic_status()` informa de cuántas hay así.
    """
    try:
        ensure_index()
    except EmbeddingsUnavailable:
        logger.exception("No se pudo calcular el embedding de la incidencia; queda pendiente.")


def semantic_status() -> dict:
    """Estado de la capa semántica: proveedor activo e incidencias pendientes de indexar."""
    embedder = get_embedder()
    total = len(store.get_all_incidents())
    pending = len(_pending(embedder))
    return {
        "provider": embedder.name,
        # True: el modelo configurado no ha cargado y se busca solo por parecido de palabras.
        "degraded": is_degraded(),
        "indexed": total - pending,
        "pending": pending,
    }


def _load_index():
    """Devuelve (incidencias, matriz): la fila i de la matriz es el vector de incidencias[i]."""
    ensure_index()
    embedder = get_embedder()
    incidents = {incident["id"]: incident for incident in store.get_all_incidents()}

    rows = []
    vectors = []
    for record in store.get_incident_embeddings():
        incident = incidents.get(record["incident_id"])
        if incident is not None and record["model"] == embedder.name:
            rows.append(incident)
            vectors.append(record["vector"])

    matrix = np.array(vectors, dtype=np.float32) if vectors else np.zeros((0, 1), dtype=np.float32)
    return rows, matrix


def _with_score(incident: dict, score: float) -> dict:
    return {
        **incident,
        "score": round(float(score), 4),
        "possible_duplicate": bool(
            score >= get_embedder().duplicate_score and incident["status"] in ACTIVE_STATUSES
        ),
    }


def _matches(incident: dict, filters: dict) -> bool:
    return all(incident[field] == value for field, value in filters.items())


def _rank(vector: np.ndarray, limit: int, filters: dict | None = None, exclude_id: int | None = None):
    """Incidencias más parecidas a `vector`, de mayor a menor similitud."""
    incidents, matrix = _load_index()
    if not incidents:
        return []

    scores = matrix @ vector
    min_score = get_embedder().min_score
    ranked = []
    for position in np.argsort(-scores):
        incident = incidents[position]
        score = scores[position]
        if score < min_score:
            break
        if incident["id"] == exclude_id or not _matches(incident, filters or {}):
            continue
        ranked.append(_with_score(incident, score))
        if len(ranked) == limit:
            break
    return ranked


def search(query: str, limit: int = 20, filters: dict | None = None) -> list[dict]:
    """Búsqueda por significado: la consulta no tiene que compartir palabras con la incidencia."""
    vector = embed([query])[0]
    return _rank(vector, limit, filters)


def similar_to_text(title: str, description: str, limit: int = 5) -> list[dict]:
    """Incidencias parecidas a un texto que todavía no se ha registrado."""
    vector = embed([incident_text(title, description)])[0]
    return _rank(vector, limit)


def similar_to_incident(incident: dict, limit: int = 5) -> list[dict]:
    """Incidencias parecidas a una ya registrada (sin incluirla a ella)."""
    vector = embed([incident_text(incident["title"], incident["description"])])[0]
    return _rank(vector, limit, exclude_id=incident["id"])


def suggest_category(neighbours: list[dict]) -> dict | None:
    """Triaje asistido: la categoría más votada por las incidencias históricas parecidas.

    Cada vecina vota con su similitud. Devuelve {"value", "confidence"} o None si no hay
    una categoría claramente dominante.
    """
    triage_score = get_embedder().triage_score
    votes = defaultdict(float)
    for neighbour in neighbours[:TRIAGE_NEIGHBOURS]:
        if neighbour["score"] >= triage_score:
            votes[neighbour["category"]] += neighbour["score"]
    if not votes:
        return None

    category, weight = max(votes.items(), key=lambda item: item[1])
    confidence = weight / sum(votes.values())
    if confidence < TRIAGE_MIN_CONFIDENCE:
        return None
    return {"value": category, "confidence": round(confidence, 2)}


def duplicate_groups() -> list[dict]:
    """Agrupa las incidencias activas (open / in_progress) que parecen el mismo problema.

    Dos incidencias se enlazan si su similitud supera el umbral de duplicado; cada grupo
    es un conjunto de incidencias enlazadas entre sí, directa o indirectamente.
    """
    incidents, matrix = _load_index()
    active = [i for i, incident in enumerate(incidents) if incident["status"] in ACTIVE_STATUSES]
    if len(active) < 2:
        return []

    vectors = matrix[active]
    linked = (vectors @ vectors.T) >= get_embedder().duplicate_score

    # Componentes conexas por búsqueda en profundidad.
    groups = []
    seen = set()
    for start in range(len(active)):
        if start in seen:
            continue
        stack = [start]
        component = []
        seen.add(start)
        while stack:
            node = stack.pop()
            component.append(node)
            for neighbour in np.flatnonzero(linked[node]):
                if int(neighbour) not in seen:
                    seen.add(int(neighbour))
                    stack.append(int(neighbour))
        if len(component) > 1:
            members = sorted((incidents[active[node]] for node in component), key=lambda i: i["created_at"])
            groups.append(
                {
                    "size": len(members),
                    "title": members[0]["title"],
                    "category": members[0]["category"],
                    "branches": sorted({member["branch"] for member in members}),
                    "origins": sorted({member["origin"] for member in members}),
                    "incident_ids": [member["id"] for member in members],
                }
            )

    groups.sort(key=lambda group: (-group["size"], group["incident_ids"][0]))
    return groups
