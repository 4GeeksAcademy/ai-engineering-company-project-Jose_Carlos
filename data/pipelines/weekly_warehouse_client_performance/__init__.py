"""Pipeline `weekly_warehouse_client_performance` (PIPELINE_DESIGN.md).

Consolidado semanal, por almacén y por cliente, del «Reporte Semanal de Desempeño por Almacén y
Cliente» de Thomas (CEO) y Ana (Head of Warehouse Operations).

Cada módulo es lógica pura que recibe sus dependencias (motor de base de datos, DataFrames,
semanas) como argumentos, para poder probarla sin Prefect. `data/pipelines/pipeline.py` la
envuelve en tasks y flows.

    extract.py     telemetry_events (solo lectura) → DataFrame de eventos
    transform.py   DataFrame de eventos → DataFrame semanal (los cuatro KPIs)
    load.py        DataFrame semanal → reporting.weekly_warehouse_client_performance (UPSERT)
    run_log.py     reporting.pipeline_runs: log de ejecución y marca de agua
    quality.py     pasos opcionales: conciliación con stock_exit y snapshot JSON
    queries.py     lecturas para services/reporting/ (sin ETL)
    trigger.py     disparo manual desde la API
"""
