"""Pipelines de datos de TrackFlow.

- `pipeline.py`: flows de Prefect (punto de entrada, también como script de CLI).
- `weekly_warehouse_client_performance/`: lógica pura del pipeline semanal por almacén y cliente
  (extracción, transformación, carga, log de ejecución, consultas). Se prueba sin Prefect.

Diseño: data/pipelines/PIPELINE_DESIGN.md.
"""
