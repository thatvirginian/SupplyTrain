-- =============================================================================
-- 2026-11-23  Employee PINs: who did it on a shared login
-- =============================================================================
-- RUN THIS BY HAND against the app's database, BEFORE deploying the code that
-- goes with it. Nothing in the app runs it for you.
--
-- Why
--   The commissary works on one shared login, so the app knows WHICH LOCATION
--   did something but not WHICH PERSON. An admin gives a Toast employee a
--   6-digit PIN. On the shared login, people clocked in on Toast tap their name
--   and enter their PIN; what they then submit is signed with their name.
--
-- What it stores (only people an admin gave a PIN; no copy of the Toast
-- employee list)
--   employee_pins          one row per person with a PIN: their Toast employee
--                          GUID (the same at every restaurant), their name as
--                          last seen in Toast, the hashed PIN, the wrong-PIN lock
--   operator_sessions      who is signed in on which device (the app ends a
--                          session after 15 idle minutes)
--   operator_signoffs      the log: who did what, on which record, when (keeps
--                          the name, so it stays readable after a PIN is removed)
--
-- What it does NOT do
--   - It changes no existing data. PINs are never stored, only a one-way hash.
--   - If an earlier test version of this file was run (tables "operators",
--     "operator_locations", "production_assignments"), those tables are removed
--     ONLY when they are empty; otherwise it stops and changes nothing.
--
-- The code that is live today keeps working after this runs.
-- Safe to run more than once.
-- =============================================================================

BEGIN;

-- Earlier test version (only if present and empty) -----------------------------
DO $$
BEGIN
    IF to_regclass('public.operators') IS NOT NULL THEN
        IF EXISTS (SELECT 1 FROM public.operators) THEN
            RAISE EXCEPTION 'An earlier version of the operators tables has data. Nothing was changed; ask before removing it.';
        END IF;
        ALTER TABLE public.production_template_items DROP COLUMN IF EXISTS default_operator_id;
        DROP TABLE IF EXISTS public.production_assignments;
        DROP TABLE IF EXISTS public.operator_signoffs;
        DROP TABLE IF EXISTS public.operator_sessions;
        DROP TABLE IF EXISTS public.operator_locations;
        DROP TABLE public.operators;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS public.employee_pins (
    id                      serial PRIMARY KEY,
    toast_employee_guid     varchar(64) NOT NULL UNIQUE,
    toast_v2_employee_guid  varchar(64),
    first_name              varchar(100),
    last_name               varchar(100),
    display_name            varchar(120) NOT NULL,      -- e.g. "Gloria C.", as last seen in Toast
    name_checked_at         timestamptz,
    pin_hash                text NOT NULL,
    pin_set_at              timestamptz NOT NULL DEFAULT now(),
    pin_set_by              varchar(256),
    failed_pin_count        integer NOT NULL DEFAULT 0,
    locked_until            timestamptz,
    last_used_at            timestamptz,
    created_at              timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.operator_sessions (
    id               serial PRIMARY KEY,
    token_hash       char(64) NOT NULL UNIQUE,         -- sha256 of the token the device holds
    employee_pin_id  integer NOT NULL REFERENCES public.employee_pins(id) ON DELETE CASCADE,
    location_id      varchar(64) NOT NULL,
    login_email      varchar(256),
    started_at       timestamptz NOT NULL DEFAULT now(),
    last_seen_at     timestamptz NOT NULL DEFAULT now(),
    ended_at         timestamptz,
    end_reason       varchar(16),
    CONSTRAINT operator_sessions_end_check
        CHECK (end_reason IS NULL OR end_reason IN ('signed_out', 'idle', 'switched'))
);
CREATE INDEX IF NOT EXISTS idx_operator_sessions_pin ON public.operator_sessions (employee_pin_id);

CREATE TABLE IF NOT EXISTS public.operator_signoffs (
    id                   bigserial PRIMARY KEY,
    toast_employee_guid  varchar(64),                    -- NULL = signed by a personal login
    signer_name          varchar(256) NOT NULL,          -- the name (or email) at the time
    login_email          varchar(256),
    location_id          varchar(64),
    action               varchar(48) NOT NULL,           -- e.g. production_run.submit
    entity_type          varchar(32) NOT NULL,           -- e.g. production_run
    entity_id            bigint NOT NULL,
    line_id              bigint,
    note                 text,
    signed_at            timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_operator_signoffs_entity
    ON public.operator_signoffs (entity_type, entity_id, signed_at DESC);
CREATE INDEX IF NOT EXISTS idx_operator_signoffs_employee
    ON public.operator_signoffs (toast_employee_guid, signed_at DESC);

COMMIT;
