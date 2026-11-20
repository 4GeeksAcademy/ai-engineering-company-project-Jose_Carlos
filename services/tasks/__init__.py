"""Cola de tareas asíncronas con Celery y Redis (hito 22, ticket #DEV-55).

- `services/celery_app.py`: la instancia de Celery (broker y backend: `REDIS_URL`).
- `base.TrackedTask`: reintentos con backoff, logs por intento y Dead Letter Queue.
- `dead_letters`: la tabla `task_dead_letters` (la DLQ, en base de datos).
- `registry`: qué tareas encoló la API y para quién (GET /tasks/{task_id} responde 404 al resto).
- `reporting`: la tarea del pipeline semanal (antes, BackgroundTasks dentro de la API).
- `router`: GET /tasks/{task_id}. Es el único módulo que importa FastAPI; el worker no lo carga.
"""
