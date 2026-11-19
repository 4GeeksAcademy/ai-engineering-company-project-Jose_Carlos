-- Dead Letter Queue de la cola de tareas (hito 22, ticket #DEV-55).
--
-- Una fila por tarea de Celery que agotó sus reintentos (max_retries = 3) o falló con un error que
-- no se reintenta. Guarda lo necesario para investigarla y, si procede, relanzarla a mano:
-- qué tarea era, con qué argumentos (solo identificadores, nunca datos voluminosos), en qué
-- intento murió y con qué error.
--
-- Idempotente: la ejecuta `services.tasks.dead_letters.ensure_dead_letter_table()` antes de la
-- primera escritura, y también se puede pegar en el SQL Editor de Supabase. Nunca borra datos.

create table if not exists public.task_dead_letters (
  id             uuid primary key default gen_random_uuid(),
  task_id        text not null,                        -- id de Celery (el que devolvió el 202)
  task_name      text not null,
  attempt        integer not null check (attempt >= 1),-- intento en el que falló (1 + reintentos)
  max_retries    integer,
  error_type     text not null,
  error_message  text not null,                        -- mensaje completo, con el traceback
  args           jsonb not null default '[]',
  kwargs         jsonb not null default '{}',
  queue          text,
  worker         text,                                 -- hostname del worker que lo ejecutó
  failed_at      timestamptz not null,                 -- cuándo falló el último intento
  created_at     timestamptz not null default now()
);

-- Una tarea solo entra una vez en la DLQ (por si el worker reintentase la escritura).
create unique index if not exists ux_task_dead_letters_task_id on public.task_dead_letters (task_id);
create index if not exists ix_task_dead_letters_failed_at on public.task_dead_letters (failed_at desc);

-- Como job_runs y telemetry_events: la API REST pública de Supabase no la lee ni la escribe.
alter table public.task_dead_letters enable row level security;
