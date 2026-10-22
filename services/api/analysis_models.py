"""Schemas Pydantic del analizador de CSV (POST /analyze).

Los nombres de campo en español (`media_satisfaccion`, `errores`) son los que devuelve
scripts/analyze.py y lee el backoffice: se mantienen para no romper el contrato.
"""

from pydantic import BaseModel


class AnalysisRowErrors(BaseModel):
    # None si la fila del CSV no tiene columna incident_id (csv.DictReader rellena con None).
    incident_id: str | None
    errors: list[str]


class AnalysisResult(BaseModel):
    valid: int
    invalid: int
    categories: dict[str, int]
    statuses: dict[str, int]
    media_satisfaccion: float
    errores: list[AnalysisRowErrors]
