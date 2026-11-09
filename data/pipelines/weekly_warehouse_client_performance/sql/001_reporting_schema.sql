-- Esquema `reporting` del pipeline weekly_warehouse_client_performance (hito 19).
--
-- Idempotente: lo ejecuta `schema.ensure_reporting_schema()` al empezar cada corrida, y también
-- se puede pegar en el SQL Editor de Supabase. Nunca toca public.telemetry_events.

create schema if not exists reporting;

-- Tabla de destino: DDL exacto del BRIEFING §5 (solo se añade `if not exists`).
create table if not exists reporting.weekly_warehouse_client_performance (
  id uuid primary key default gen_random_uuid(),
  warehouse text not null,
  client_id text not null,
  week_start date not null,
  inbound_units_count integer not null default 0,
  outbound_orders_count integer not null default 0,
  stockout_events_count integer not null default 0,
  discrepancy_events_count integer not null default 0,
  discrepancy_rate numeric not null default 0,
  computed_at timestamptz not null default now(),
  unique (warehouse, client_id, week_start)
);

create index if not exists ix_wwcp_week_start
  on reporting.weekly_warehouse_client_performance (week_start);

-- Guardas aditivas (PIPELINE_DESIGN.md §7.1): no cambian columnas ni el constraint unique.
do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'ck_wwcp_warehouse') then
    alter table reporting.weekly_warehouse_client_performance
      add constraint ck_wwcp_warehouse check (warehouse in ('los_angeles', 'zaragoza'));
  end if;
  if not exists (select 1 from pg_constraint where conname = 'ck_wwcp_week_start') then
    alter table reporting.weekly_warehouse_client_performance
      add constraint ck_wwcp_week_start check (extract(isodow from week_start) = 1);
  end if;
  if not exists (select 1 from pg_constraint where conname = 'ck_wwcp_rate') then
    alter table reporting.weekly_warehouse_client_performance
      add constraint ck_wwcp_rate check (discrepancy_rate >= 0);
  end if;
end $$;

-- Igual que telemetry_events: la API REST pública de Supabase no la lee ni la escribe.
alter table reporting.weekly_warehouse_client_performance enable row level security;

-- Log de ejecución y tabla de control de la marca de agua (PIPELINE_DESIGN.md §9).
create table if not exists reporting.pipeline_runs (
  run_id               uuid primary key,
  pipeline_name        text not null,
  trigger              text not null check (trigger in ('scheduled', 'manual', 'backfill')),
  triggered_by         text,
  status               text not null check (status in ('running', 'completed', 'failed')),
  started_at           timestamptz not null default now(),
  finished_at          timestamptz,
  weeks_processed      jsonb not null default '[]',
  source_watermark     timestamptz not null,
  events_extracted     integer not null default 0,
  events_discarded     integer not null default 0,
  events_deduplicated  integer not null default 0,
  rows_upserted        integer not null default 0,
  rows_deleted         integer not null default 0,
  error_stage          text check (error_stage in ('start', 'extract', 'transform', 'load', 'crashed')),
  error_message        text,
  warnings             jsonb not null default '[]',
  parameters           jsonb not null default '{}',
  code_version         text,
  check (status = 'running' or finished_at is not null),
  check (status <> 'failed' or error_stage is not null)
);

-- Como mucho una corrida en curso por pipeline: un segundo disparo falla al insertar.
create unique index if not exists ux_pipeline_runs_one_running
  on reporting.pipeline_runs (pipeline_name) where status = 'running';

-- Última corrida y última corrida correcta (marca de agua).
create index if not exists ix_pipeline_runs_latest
  on reporting.pipeline_runs (pipeline_name, started_at desc);

alter table reporting.pipeline_runs enable row level security;
