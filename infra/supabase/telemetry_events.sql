-- telemetry_events: almacenamiento de la telemetría de TrackFlow (hito 16).
--
-- La API crea esta tabla sola al arrancar (services/database.py → create_db_and_tables, a
-- partir de services/telemetry_models.py). Este script es el mismo DDL para ejecutarlo a mano
-- en el SQL Editor de Supabase; es idempotente. tests/telemetry/test_telemetry_storage.py
-- comprueba que no se separa del modelo.

CREATE TABLE IF NOT EXISTS telemetry_events (
    id          UUID                     NOT NULL,              -- eventId (idempotencia)
    event_type  TEXT                     NOT NULL,
    timestamp   TIMESTAMP WITH TIME ZONE NOT NULL,              -- momento de la captura
    session_id  TEXT,
    user_id     TEXT,
    source      TEXT                     NOT NULL,
    tags        JSONB                    NOT NULL,              -- properties + environment, schema_version, request_id
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, -- momento de la ingesta
    PRIMARY KEY (id),
    CONSTRAINT ck_telemetry_events_source CHECK (source IN ('api', 'backoffice_web'))
);

-- Los tres índices que hacen la tabla consultable a escala.
CREATE INDEX IF NOT EXISTS ix_telemetry_events_timestamp ON telemetry_events (timestamp);
CREATE INDEX IF NOT EXISTS ix_telemetry_events_event_type ON telemetry_events (event_type);
CREATE INDEX IF NOT EXISTS ix_telemetry_events_tags ON telemetry_events USING gin (tags);

-- Sin políticas: la API REST de Supabase (clave pública) no puede leer ni escribir.
ALTER TABLE telemetry_events ENABLE ROW LEVEL SECURITY;

-- Inmutable: ningún UPDATE, DELETE ni TRUNCATE, ni siquiera del propietario.
CREATE OR REPLACE FUNCTION telemetry_events_reject_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION USING
        MESSAGE = 'telemetry_events es inmutable: ' || TG_OP || ' no está permitido',
        ERRCODE = 'insufficient_privilege';
END;
$$;

DROP TRIGGER IF EXISTS telemetry_events_immutable_rows ON telemetry_events;
CREATE TRIGGER telemetry_events_immutable_rows BEFORE UPDATE OR DELETE ON telemetry_events
    FOR EACH ROW EXECUTE FUNCTION telemetry_events_reject_change();

DROP TRIGGER IF EXISTS telemetry_events_immutable_table ON telemetry_events;
CREATE TRIGGER telemetry_events_immutable_table BEFORE TRUNCATE ON telemetry_events
    FOR EACH STATEMENT EXECUTE FUNCTION telemetry_events_reject_change();
