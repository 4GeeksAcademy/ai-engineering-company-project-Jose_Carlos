"""Reporting de negocio: endpoints del pipeline de desempeño semanal (hito 19).

La lógica vive en data/pipelines/; este módulo solo la expone por HTTP (ver router.py).
"""

from services.reporting.router import router

__all__ = ["router"]
